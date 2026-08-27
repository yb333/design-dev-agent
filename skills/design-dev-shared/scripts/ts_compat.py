# -*- coding: utf-8 -*-
"""ts.json 两视图结构：字段分桶分类原语 + 旧结构升级（幂等）。

2026-08 两视图重构（唯一分界：这个键回答"表是什么"还是"规则怎么产"）：
- tables = 纯表元数据（字段名/类型/注释 + 物理属性），DDL 唯一源
- rules.fields = 加工三桶 {processed:[{target,logic,refs}], assign:[{target,value}],
  direct:["a.col AS x"]}——coder 唯一消费源；桶名即分类（无细分 transform_type）
桶判据 = coder 对该字段是粘贴还是写表达式；直取串一律带 AS（粘贴零加工），串即完整血缘。
旧结构（tables.fields 带加工语义 + rules 带 field_logics/source_refs）由
normalize_ts 内存升级，opt 读存量 baseline 等场景用。
"""

import copy

from dws_standards import STANDARD_AUDIT_TEMPLATE, STANDARD_AUDIT_NAMES


def slim_field(f: dict) -> dict:
    """字段对象 → tables 三键条目（名/类型/注释）。"""
    return {k: f.get(k, "") for k in ("target_field", "field_type", "field_comment")}


def classify_field(f: dict, logic_override: str = None):
    """字段对象（build_field 产物 / 旧 ts 字段，同形态）→ (tables条目, 桶名, 桶条目)。

    - direct 有源 → direct 串 "alias.col AS target"（一律带 AS，同名也写）
    - assign → {"target", "value"}（value 从"固定赋值 X"提取，否则用 design_logic 原文）
    - 其余（加工 / 无源直取的自建与占位）→ processed {"target","logic","refs"}
      （refs = source_fields 的 "alias.field" 串列表 = 完整血缘）
    """
    target = f.get("target_field", "")
    tt = f.get("transform_type", "direct")
    sfs = f.get("source_fields") or []
    if logic_override is not None:
        # designer 显式写了口径 → 强制 processed（口径优先，不受 rs_input 分类影响——
        # 即便字段在 mapping 里是直取/赋值，写了 field_logics 就按他的口径加工）
        refs, seen = [], set()
        for sf in sfs:
            a = (sf.get("alias") or sf.get("table") or "").strip()
            c = (sf.get("field") or "").strip()
            r = f"{a}.{c}" if a and c else (c or a)
            if r and r not in seen:
                seen.add(r)
                refs.append(r)
        return slim_field(f), "processed", {"target": target, "logic": str(logic_override), "refs": refs}
    logic = f.get("design_logic", "")
    if tt == "direct" and sfs:
        s0 = sfs[0]
        alias = (s0.get("alias") or s0.get("table") or "").strip()
        col = (s0.get("field") or "").strip()
        if col:
            ref = f"{alias}.{col}" if alias else col
            # 一律带 AS（coder 规范：输出字段必须显式命名，check_sql 靠 AS 对账——
            # 同名也写，粘贴零加工）
            return slim_field(f), "direct", f"{ref} AS {target}"
    if tt == "assign":
        v = str(logic)
        if v.startswith("固定赋值 "):
            v = v[len("固定赋值 "):]
        return slim_field(f), "assign", {"target": target, "value": v}
    refs, seen = [], set()
    for s in sfs:
        a = (s.get("alias") or s.get("table") or "").strip()
        c = (s.get("field") or "").strip()
        r = f"{a}.{c}" if a and c else (c or a)
        if r and r not in seen:
            seen.add(r)
            refs.append(r)
    return slim_field(f), "processed", {"target": target, "logic": str(logic), "refs": refs}


def audit_value_map(design: dict) -> dict:
    """4 个标准审计的标准值（design.audit_fields 归一值，兜底模板）。"""
    out = {}
    afs = (design or {}).get("audit_fields") or {}
    for name, spec in STANDARD_AUDIT_TEMPLATE.items():
        out[name] = (afs.get(name) or {}).get("default") or spec.get("default", "")
    return out


def normalize_ts(ts: dict) -> dict:
    """旧结构 ts → 新两视图结构（返回新 dict 不改入参；新结构幂等原样返回）。

    处理：tables.fields 瘦身三键；rules/init.rules 产三桶（field_logics 覆盖口径、
    缺失审计补 assign 标准值）、删 field_logics/source_refs。
    """
    rules = ts.get("rules") or {}
    if not isinstance(rules, dict):
        return ts
    tables = ts.get("tables") or {}
    old_fields_semantic = any(
        ("design_logic" in f) or ("transform_type" in f)
        for t in tables.values() if isinstance(t, dict)
        for f in (t.get("fields") or []) if isinstance(f, dict))
    all_bucketed = rules and all(isinstance(r.get("fields"), dict) for r in rules.values())
    if all_bucketed and not old_fields_semantic:
        return ts  # 已是新结构

    ts = dict(ts)
    # 语义登记：tables.fields ∪ 各规则自带 fields（远古格式语义挂在 rule 上，无 tables）
    tbl_fields = {}
    for tname, t in tables.items():
        if isinstance(t, dict):
            tbl_fields[tname.lower()] = {
                str(f.get("target_field", "")).lower(): f
                for f in (t.get("fields") or []) if isinstance(f, dict)}
    for r in rules.values():
        if isinstance(r, dict) and isinstance(r.get("fields"), list):
            tshort = str(r.get("target_table") or "").rsplit(".", 1)[-1].lower()
            m = tbl_fields.setdefault(tshort, {})
            for f in r["fields"]:
                if isinstance(f, dict) and f.get("target_field"):
                    m.setdefault(str(f["target_field"]).lower(), f)
    avm = audit_value_map(ts.get("design") or {})
    ts["tables"] = {
        tname: dict(t, fields=[slim_field(f) for f in (t.get("fields") or [])])
        for tname, t in tables.items() if isinstance(t, dict)}

    def _norm_rule(r: dict) -> dict:
        if not isinstance(r, dict) or isinstance(r.get("fields"), dict):
            return r
        r = dict(r)
        logics = r.pop("field_logics", None) or {}
        r.pop("source_refs", None)
        tshort = str(r.get("target_table") or "").rsplit(".", 1)[-1].lower()
        fmap = tbl_fields.get(tshort, {})
        targets = r.get("field_targets")
        if targets is None:  # 远古格式：没有 field_targets，目标就是 rule.fields 列表
            _rf = r.get("fields")
            targets = ([f.get("target_field", "") for f in _rf if isinstance(f, dict)]
                       if isinstance(_rf, list) else [])
        buckets = {"processed": [], "assign": [], "direct": []}
        seen = set()
        for t in targets:
            f = fmap.get(str(t).lower())
            if not f:
                continue
            _, kind, entry = classify_field(f, logic_override=logics.get(t))
            buckets[kind].append(entry)
            seen.add(str(t).lower())
        for aname in STANDARD_AUDIT_NAMES:
            if aname not in seen:
                buckets["assign"].append({"target": aname, "value": avm.get(aname, "")})
        r["fields"] = buckets
        if r.get("field_targets") is None:
            r["field_targets"] = list(targets)
        return r

    ts["rules"] = {code: _norm_rule(r) for code, r in rules.items()}
    init = ts.get("init")
    if isinstance(init, dict) and isinstance(init.get("rules"), dict):
        ts["init"] = dict(init, rules={c: _norm_rule(r) for c, r in init["rules"].items()})
    return ts
