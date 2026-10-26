"""assemble_ts_opt —— 优化模式 ts 组装器（docs/specs/opt/04 §二）。

ts_baseline + 增量 decisions → ts_v2（完整结构 + change 段）。
★ 独立脚本，不改 assemble_ts.py（零存量接触）；ts 结构消费与 fence_check 对齐。

增量 decisions（designer 产出，YAML——模板见 dws-design-opt/assets/opt-decisions-template.yaml）：
只写增量，不写存量（重写存量 = 重写存量设计，红线禁止）。每个新增字段一条：
挂哪条规则 / 血缘 / 新 JOIN 及其 safety（新 JOIN 必须声明——04 §一第3步）/ 回刷意向。

应用是确定性的：decisions 说的才落，ts_baseline 的存量一个字节不动。
产出 ts_v2 后由 pipe 跑 fence_check 审计（本脚本不自审——被审计者不当审计员）。

用法：
  python assemble_ts_opt.py --ts-baseline {ts_baseline.json} \
      --decisions {design_decisions_opt.yaml} --output {ts_v2.json}
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from sql_parse import (parse_join_pairs, find_unqualified_refs, find_three_part_refs,
                       extract_qualified_refs, extract_logic_refs)
from type_compat import join_key_pair_risky, types_compatible

# decisions 必填键（缺 = fail loud，防 designer 漏声明）
FIELD_REQUIRED_KEYS = ("field", "target_table", "placed_rules", "field_type",
                       "field_comment", "design_logic")
JOIN_REQUIRED_KEYS = ("rule", "table", "alias", "join_type", "on", "join_safety")

TS_RESERVED_RULE_KEYS = {"field_targets", "field_logics", "joins", "join_safety",
                         "source_tables"}


def _fail(msg: str) -> None:
    print(f"[ASSEMBLE_OPT_ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def load_decisions(path: Path) -> dict:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if d.get("change_type") != "add_field":
        _fail(f"decisions.change_type = {d.get('change_type')!r}，本刀仅支持 add_field"
              f"（modify_types 作为并行段声明——change_type 保持 add_field 兼容锚）")
    if not d.get("fields") and not d.get("modify_types") and not d.get("modify_logics"):
        _fail("decisions.fields / modify_types / modify_logics 均为空——没有要落的变更")
    return d


def _ref_domains(ts_baseline: dict, new_joins: list) -> Tuple[dict, dict]:
    """口径引用解析域（N38 等价用）：(cache 域, 声明域)。

    cache 域：alias → (schema, table)（小写）——baseline 全部规则源表 ∪ 本字段
    new_joins 声明，查 schema_cache（precheck_opt 拉「新源∪baseline 全部源表」落盘）。
    声明域：短表名 → 字段集——ts tables（目标/中间表，我们建的结构在档），
    不依赖连库。"""
    cache_domain: dict = {}
    for r in (ts_baseline.get("rules") or {}).values():
        for s in r.get("source_tables") or []:
            if s.get("alias") and s.get("table"):
                cache_domain[str(s["alias"]).lower()] = (str(s.get("schema", "")).lower(),
                                                         str(s["table"]).lower())
    for j in new_joins or []:
        if j.get("alias") and j.get("table"):
            cache_domain[str(j["alias"]).lower()] = (str(j.get("schema", "")).lower(),
                                                     str(j["table"]).lower())
    declared_domain = {str(t).lower(): {str(f.get("target_field", "")).lower()
                                        for f in (td.get("fields") or [])
                                        if isinstance(f, dict) and f.get("target_field")}
                       for t, td in (ts_baseline.get("tables") or {}).items()}
    return cache_domain, declared_domain


def _check_logic_ref_existence(logic: str, label: str, ts_baseline: dict,
                               new_joins: list, cache: Optional[dict]) -> None:
    """N38 等价（2026-10-23 缺 a 补齐）：新口径限定引用查表存在性——源表查
    schema_cache、目标/中间表查 ts 结构声明集，幻觉列硬拦（引用幻觉此前只能等
    UT 炸，回路最长）。别名两头解析不了 → 跳过不猜（宁放过，同 new-pipe）；
    cache None（无库未建缓存）→ 源表侧跳过（声明域仍查——结构在档零成本）。"""
    if not logic:
        return
    cache_domain, declared_domain = _ref_domains(ts_baseline, new_joins)
    for al, c in extract_logic_refs(logic, set())[0]:
        key = cache_domain.get(al)
        if key is not None:
            fields = (cache or {}).get(key)
            if fields is not None and c not in {str(k).lower() for k in fields}:
                _fail(f"{label} 的口径引用 {al}.{c}，源表 {key[0]}.{key[1]} 里没有字段 "
                      f"'{c}'——检查拼写（引用确认可调 explore 批量模式 --ts 锚点）")
        elif al in declared_domain:
            if c not in declared_domain[al]:
                _fail(f"{label} 的口径引用 {al}.{c}，表 {al}（ts 结构声明集）里没有字段 "
                      f"'{c}'——检查拼写")
        # 两头都解析不了 → 宁放过（N36 已保证格式；无绑定别名归 designer 判断域）


def validate_modify_logics(decisions: dict, ts_baseline: dict,
                           cache: Optional[dict] = None) -> None:
    """modify_logics 段合法性（第三刀·2026-10-22 口径修改）：字段必须是 baseline
    存量、桶中必须有旧条目（有落点可改）、new_logic 非空且过引用门禁
    （N36 等价——designer 翻译的新口径必须可结构化解析；N38 等价 2026-10-23 补——
    限定引用查 schema_cache/ts 结构声明集，幻觉列当场拦）。"""
    fields = ts_baseline.get("tables", {})
    for i, m in enumerate(decisions.get("modify_logics") or [], start=1):
        for k in ("field", "target_table", "new_logic"):
            if not m.get(k):
                _fail(f"modify_logics[{i}] 缺必填项 {k!r}（新口径=designer 翻译后的"
                      f" design_logic——人话原文在 change_request.modify_logic_fields）")
        if m["target_table"] not in fields:
            _fail(f"modify_logics[{i}].target_table {m['target_table']!r} 不在 baseline 表集")
        bf = {x["target_field"] for x in fields[m["target_table"]].get("fields", [])}
        if m["field"] not in bf:
            _fail(f"modify_logics[{i}].field {m['field']!r} 不在 {m['target_table']} 存量字段"
                  f"——口径修改只针对存量（新字段在 fields 段直接写对口径）")
        _old = _locate_logic_entries(ts_baseline, m["field"])
        if not _old:
            _fail(f"modify_logics[{i}].field {m['field']!r} 在 baseline 规则桶中无条目"
                  f"（无落点可改——确认字段归属）")
        logic = m.get("new_logic") or ""
        three = find_three_part_refs(logic)
        if three:
            _fail(f"modify_logics[{i}].new_logic 含三段式引用 {three}——口径引用一律'别名.字段'两段")
        bare = find_unqualified_refs(logic)
        if bare:
            _fail(f"modify_logics[{i}].new_logic 含未限定标识符 {bare}——字段引用写'别名.字段'"
                  f"（未限定归属是设计判断，脚本不猜）")
        # N38 等价（2026-10-23 缺 a）：新口径引用查存在——幻觉列当场拦
        _check_logic_ref_existence(logic, f"modify_logics[{i}].new_logic",
                                   ts_baseline, [], cache)


def _locate_logic_entries(ts_baseline: dict, field: str) -> list:
    """baseline 规则桶中该字段的全部条目 [(rule, kind, entry)]——口径修改的落点
    （processed 条目 logic 替换 / direct 串迁移为 processed）。"""
    out = []
    for code, r in (ts_baseline.get("rules") or {}).items():
        buckets = r.get("fields") or {}
        for p in (buckets.get("processed") or []):
            if isinstance(p, dict) and str(p.get("target", "")).lower() == field.lower():
                out.append((code, "processed", p))
        for d in (buckets.get("direct") or []):
            t = str(d).rsplit(" AS ", 1)[-1].strip().lower() if " AS " in str(d) else ""
            if t == field.lower():
                out.append((code, "direct", d))
    return out


def validate_modify_types(decisions: dict, ts_baseline: dict) -> None:
    """modify_types 段合法性（场景 B·2026-10-22）：字段必须是 baseline 存量、
    新旧类型归一比必须不同（同类型无意义）、目标表合法。"""
    fields = ts_baseline.get("tables", {})
    for i, m in enumerate(decisions.get("modify_types") or [], start=1):
        for k in ("field", "target_table", "old_type", "new_type"):
            if not m.get(k):
                _fail(f"modify_types[{i}] 缺必填项 {k!r}（照抄 change_request.modify_type_fields，"
                      f"含 decision 标记勿推翻）")
        if m["target_table"] not in fields:
            _fail(f"modify_types[{i}].target_table {m['target_table']!r} 不在 baseline 表集")
        bf = {x["target_field"]: x for x in fields[m["target_table"]].get("fields", [])}
        if m["field"] not in bf:
            _fail(f"modify_types[{i}].field {m['field']!r} 不在 {m['target_table']} 存量字段"
                  f"——类型修改只针对存量（新字段在 fields 段直接写对类型）")
        if not types_compatible(m["old_type"], bf[m["field"]].get("field_type", "")):
            _fail(f"modify_types[{i}].old_type {m['old_type']!r} 与 baseline 类型不一致"
                  f"（{bf[m['field']].get('field_type')!r}，归一比较）——照抄"
                  f" change_request 的 old_type")
        if types_compatible(m["old_type"], m["new_type"]):
            _fail(f"modify_types[{i}] 新旧类型归一后相同（{m['old_type']!r} vs {m['new_type']!r}）"
                  f"——无意义的类型修改")


def validate_decisions(decisions: dict, ts_baseline: dict, cache: dict | None = None) -> None:
    """decisions 自身合法性（与 ts_baseline 的对接面），fail loud。
    cache: schema_cache（{(schema,table): {col:type}}）——新 JOIN 类型比对用；
    None = 无缓存（比对降级，打印 warn 不硬拦——宁放过不误报）。"""
    fields = ts_baseline.get("tables", {})
    rules = ts_baseline.get("rules", {})
    target_asset = ts_baseline["meta"]["target"]["f_table"]["table"]

    for i, f in enumerate(decisions["fields"], start=1):
        for k in FIELD_REQUIRED_KEYS:
            if not f.get(k):
                _fail(f"fields[{i}] 缺必填项 {k!r}（模板见 dws-design-opt/assets/opt-decisions-template.yaml）")
        if f["target_table"] not in fields:
            _fail(f"fields[{i}].target_table {f['target_table']!r} 不在 baseline 表集")
        if f["field"] in {x["target_field"] for x in fields[f["target_table"]]["fields"]}:
            _fail(f"fields[{i}].field {f['field']!r} 已存在于 {f['target_table']}——存量字段")
        if f["target_table"] == target_asset and "placed_rules" not in f:
            pass
        for t in f.get("intermediate_tables", []):
            if t not in fields:
                _fail(f"fields[{i}].intermediate_tables 含未知表 {t!r}")
        for r in f["placed_rules"]:
            if r not in rules:
                _fail(f"fields[{i}].placed_rules 含未知规则 {r!r}")
        for j in f.get("new_joins", []):
            for k in JOIN_REQUIRED_KEYS:
                if k not in j or (k != "join_safety" and not j.get(k)):
                    _fail(f"fields[{i}].new_joins 缺必填项 {k!r}——新 JOIN 必须完整声明"
                          f"（含 join_safety，04 §一第3步）")
            if j["rule"] not in f["placed_rules"]:
                _fail(f"fields[{i}].new_joins.rule {j['rule']!r} 不在 placed_rules——"
                      f"新 JOIN 只能挂落位规则")
            js = j.get("join_safety") or {}
            if not js.get("strategy"):
                _fail(f"fields[{i}].new_joins[{j['alias']}].join_safety.strategy 为空")
            if "join_key_unique" not in js:
                _fail(f"fields[{i}].new_joins[{j['alias']}].join_safety.join_key_unique 缺失"
                      f"——断言必须有结论（true/false）")
            if not str(js.get("reason") or "").strip():
                _fail(f"fields[{i}].new_joins[{j['alias']}].join_safety.reason 为空——断言必须"
                      f"有依据句（--eval 实测数字直贴/输入声明/主键论证；连不上库=reason 标注"
                      f"「未实测」+输入依据，不静默空——与新建评估层同款纪律：先取证后断言）")

        # ★ 引用门禁（N36 等价，2026-09-04 补）：design_logic 剥全角说明后——
        # 三段式硬拦 / 未限定英文标识符拦（产出必须 100% 可结构化解析）
        logic = f.get("design_logic") or ""
        three = find_three_part_refs(logic)
        if three:
            _fail(f"fields[{i}].design_logic 含三段式引用 {three}——口径引用一律'别名.字段'两段")
        bare = find_unqualified_refs(logic)
        if bare:
            _fail(f"fields[{i}].design_logic 含未限定标识符 {bare}——字段引用写'别名.字段'"
                  f"（未限定归属是设计判断，脚本不猜）")
        # N38 等价（2026-10-23 缺 a）：新字段口径引用查存在（解析域含本字段 new_joins
        # 声明的新源——新 JOIN 还没落 ts，从 decisions 现取）
        _check_logic_ref_existence(logic, f"fields[{i}].design_logic",
                                   ts_baseline, f.get("new_joins") or [], cache)

        # ★ 新 JOIN 键类型比对（N_JOIN2 等价，2026-09-04 补）：ON 等值对两侧类型
        # 跨大类须内联 cast（on 里 :: / cast()）；类型走 schema_cache（无 cache 降 warn 不硬拦）
        if cache is not None:
            _validate_join_types(f, i, ts_baseline, cache)


def _validate_join_types(f: dict, i: int, ts_baseline: dict, cache: dict) -> None:
    """ON 等值对两侧类型比对（跨大类须 cast——对齐 new-pipe N_JOIN2 语义）。

    类型域：schema_cache（{(schema,table): {col: type}}）；alias 解析域 = baseline
    全部规则源表 ∪ 本字段 new_joins 声明。查不到类型的对跳过（宁放过不误报）。
    """
    idx = {}
    for r in (ts_baseline.get("rules") or {}).values():
        for s in r.get("source_tables") or []:
            if s.get("alias"):
                idx[str(s["alias"]).lower()] = (s.get("schema", ""), s.get("table", ""))
    for j in f.get("new_joins", []):
        idx[str(j.get("alias", "")).lower()] = (j.get("schema", ""), j.get("table", ""))
    for j in f.get("new_joins", []):
        on = j.get("on") or ""
        for (a1, c1), (a2, c2) in parse_join_pairs(on):
            sides = []
            for al, c in ((a1, c1), (a2, c2)):
                st = idx.get(al)
                ty = ""
                if st:
                    ty = (cache.get((st[0].lower(), st[1].lower())) or {}).get(c, "")
                sides.append((f"{al}.{c}", ty))
            if sides[0][1] and sides[1][1] and \
                    join_key_pair_risky(sides[0][1], sides[1][1]):
                has_cast = "::" in on or "cast(" in on.lower()
                if not has_cast:
                    _fail(f"fields[{i}].new_joins[{j.get('alias')}] 的 ON 键类型跨大类"
                          f"（{sides[0][0]}:{sides[0][1]} vs {sides[1][0]}:{sides[1][1]}）"
                          f"——须内联 cast（如 a.code::numeric）或改键；键类型以库为准"
                          f"（precheck_opt 已对账）")


def apply_decisions(ts_baseline: dict, decisions: dict) -> dict:
    """确定性应用：decisions 说的才落，存量不动。返回 ts_v2（含 change 段）。"""
    from ts_compat import normalize_ts
    v2 = normalize_ts(json.loads(json.dumps(ts_baseline)))  # 深拷贝 + 升级两视图（幂等）
    v2["generated_by"] = "assemble_ts_opt"
    change_fields = []

    for f in decisions["fields"]:
        fname = f["field"]
        # 1. 目标表 + 中间表字段定义
        # 新字段按两视图落：tables 三键元数据 + 规则桶（designer 写了口径 → processed）
        def make_field(ttype_comment=True):
            return {
                "target_field": fname,
                "field_type": f["field_type"] if ttype_comment else "",
                "field_comment": f["field_comment"] if ttype_comment else "",
            }
        v2["tables"][f["target_table"]]["fields"].append(make_field())
        for t in f.get("intermediate_tables", []):
            v2["tables"][t]["fields"].append(make_field(ttype_comment=False))

        # 2. 落位规则：field_targets 投影 + fields 桶（design_logic → processed）
        for r in f["placed_rules"]:
            rule = v2["rules"][r]
            # 保序追加（不 sorted 重排）：存量序冻结自档案——重排会让 archive↔tmp 的行级
            # diff 出现存量重排噪音；确定性 diff = 存量字节不变 + 新字段固定尾部追加
            _targets = list(rule.get("field_targets") or [])
            if fname not in _targets:
                _targets.append(fname)
            rule["field_targets"] = _targets
            _src = f.get("source") or {}
            _ref = f"{_src.get('alias','')}.{_src.get('field', fname)}".strip(".")
            rule.setdefault("fields", {"processed": [], "assign": [], "direct": []})["processed"].append(
                {"target": fname, "logic": f["design_logic"], "refs": [_ref] if _ref else []})

        # 3. 新 JOIN：joins / source_tables / join_safety / meta 源表 / data_flow 节点
        for j in f.get("new_joins", []):
            rule = v2["rules"][j["rule"]]
            rule["joins"].append({"alias": j["alias"], "type": j["join_type"],
                                  "condition": j["on"], "filter": ""})
            rule["source_tables"].append({"schema": j.get("schema", ""),
                                          "table": j["table"], "alias": j["alias"]})
            js = j["join_safety"]
            rule["join_safety"].append({
                "table": j["table"], "join_filter": js.get("join_filter", ""),
                "join_key_unique": bool(js.get("join_key_unique", False)),
                "strategy": js.get("strategy", ""), "reason": js.get("reason", ""),
            })
            if not any(s.get("table") == j["table"]
                       for s in v2["meta"]["source_tables"]):
                v2["meta"]["source_tables"].append({
                    "schema": j.get("schema", ""), "table": j["table"],
                    "table_cn": "", "alias": j["alias"]})
            if not any(n.get("name") == j["table"]
                       for n in v2["data_flow"]["tables"]):
                v2["data_flow"]["tables"].append({
                    "schema": j.get("schema", ""), "name": j["table"],
                    "role": "source", "layer": "", "is_view": False})

        # 4. 派生计数
        tgt = f["target_table"]
        v2["meta"]["field_count"]["business"] += 1
        v2["meta"]["field_count"]["total"] += 1

        change_fields.append({
            "field": fname, "target_table": tgt,
            "field_type": f["field_type"], "field_comment": f["field_comment"],
            "design_logic": f["design_logic"],
            "placed_rules": list(f["placed_rules"]),
            "intermediate_tables": list(f.get("intermediate_tables", [])),
            "new_joins": [{k: j[k] for k in ("rule", "table", "alias", "on")}
                          for j in f.get("new_joins", [])],
            "source": f.get("source") or {},   # 血缘（alias.field）——patcher 写 TargetFields 用
            "backfill": decisions.get("backfill", f.get("backfill", "pending")),
        })

    # 5. change 段（fence_check 的消费形状；结构见 fence_check 模块头注释）
    # backfill 顶层（gate_summary_opt 读这里）：YAML 布尔归一为语义值（no=无需回刷）
    _bf = decisions.get("backfill", "pending")
    _bf = "no" if _bf is False else (str(_bf) if _bf else "pending")
    v2["change"] = {"change_type": "add_field", "backfill": _bf, "fields": change_fields}

    # 6. 场景 B（2026-10-22）：类型修改落地——tables 当前态=终态（field_type 更新），
    # change.modify_types 留声明（围栏恰好性/DDL 变更单/切片 coder cast/patch 的锚）
    _mods = []
    for m in decisions.get("modify_types") or []:
        _tf = {x["target_field"]: x for x in v2["tables"][m["target_table"]]["fields"]}
        if m["field"] in _tf:
            _tf[m["field"]]["field_type"] = m["new_type"]
        _mods.append({k: m.get(k, "") for k in ("field", "target_table",
                                                "old_type", "new_type")}
                     | {"decision": m.get("decision", "")})
    if _mods:
        v2["change"]["modify_types"] = _mods

    # 7. 第三刀（2026-10-22）：口径修改落地——桶条目自动定位（脚本确定性动作，
    # designer 只翻新口径）：processed 条目 logic 替换 / direct 串迁移为 processed
    # （直取→加工，桶归属变化是口径修改的合法形态）
    _mlogics = []
    for m in decisions.get("modify_logics") or []:
        fname = m["field"]
        for code, kind, entry in _locate_logic_entries(v2, fname):
            buckets = v2["rules"][code].setdefault(
                "fields", {"processed": [], "assign": [], "direct": []})
            if kind == "processed":
                entry["logic"] = m["new_logic"]
            else:  # direct 串 → processed 条目（迁移：删 direct 追 processed）
                buckets["direct"] = [d for d in buckets["direct"] if d != entry]
                buckets["processed"].append({"target": fname, "logic": m["new_logic"],
                                             "refs": [str(entry).rsplit(" AS ", 1)[0].strip()]})
        _mlogics.append({
            "field": fname, "target_table": m.get("target_table", ""),
            "old_logic": m.get("old_logic", ""), "new_logic": m["new_logic"],
            "rules": sorted({c for c, _k, _e in _locate_logic_entries(ts_baseline, fname)}),
            "reason": m.get("reason", ""),
        })
    if _mlogics:
        v2["change"]["modify_logics"] = _mlogics
    return v2


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化模式组装：ts_baseline + 增量decisions → ts_v2")
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--decisions", required=True, help="design_decisions_opt.yaml")
    ap.add_argument("--output", required=True, help="ts_v2.json 输出路径")
    ap.add_argument("--schema-cache", default="", help="schema_cache.json 路径（默认 decisions 同目录）")
    args = ap.parse_args(argv)

    ts_baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    decisions = load_decisions(Path(args.decisions))
    # schema_cache：默认 decisions 同目录（precheck_opt 步骤 1b 落的）；显式 --schema-cache 覆盖
    cache_path = (Path(args.schema_cache) if args.schema_cache
                  else Path(args.decisions).parent / "schema_cache.json")
    cache = None
    if cache_path.exists():
        try:
            _c = json.loads(cache_path.read_text(encoding="utf-8")).get("tables", {})
            cache = {k: v for k, v in _c.items()}
        except Exception:
            cache = None
    if cache is None:
        print("WARN: 无 schema_cache——新 JOIN 键类型比对降级跳过（precheck_opt 连库后会落缓存）",
              file=sys.stderr)
    validate_decisions(decisions, ts_baseline, cache)
    validate_modify_types(decisions, ts_baseline)
    validate_modify_logics(decisions, ts_baseline, cache)
    v2 = apply_decisions(ts_baseline, decisions)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")
    # ts.md 同步产出（当前态完整性：档案 ts.json/ts.md 成对）——投影件，渲染失败不阻断组装。
    # 文件名按产出标准 {资产短名}_ts.md（与主线 assemble_ts 同标准，消费方统一寻址）
    try:
        from assemble_ts import render_md
        _short = (((v2.get("meta", {}) or {}).get("target", {}) or {})
                  .get("f_table", {}) or {}).get("table") or "ts"
        md_path = out.parent / f"{_short}_ts.md"
        md_path.write_text(render_md(v2), encoding="utf-8")
        print(f"ts_md: {md_path}")
    except Exception as e:
        print(f"WARN: ts.md 渲染失败（不阻断）: {e}", file=sys.stderr)
    n_joins = sum(len(f.get("new_joins", [])) for f in decisions["fields"])
    print(f"ts_v2: {out}")
    print(f"fields: {len(decisions['fields'])}, new_joins: {n_joins}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
