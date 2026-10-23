"""fence_check —— ts 级围栏：声明驱动的冻结层比对引擎（docs/specs/opt/03 §三）。

三段审计链的第二段（落位→结构）：diff(ts_v2, ts_baseline) 的每个变更项必须被
变更声明罩住（正向：越界=硬阻断）；声明的每条必须在 diff 中有落点（反向：漏改=硬阻断）。
"恰好等于"的双向性。

声明来源（两级合体）：
- change_request.json（业务级，preprocess_opt 产出）
- ts_v2.change 段（设计落位，designer 声明——本模块定义其消费形状）：
    "change": {
      "change_type": "add_field",
      "fields": [
        { "field": "channel_name", "target_table": "dwb_trade_order_d",
          "placed_rules": ["R0001", "R0002"],      # 落位：哪些规则产出/携带该字段
          "intermediate_tables": ["tmp_trade_order"],   # 穿中间表时列出（可空）
          "new_joins": [ {"rule": "R0002", "table": "dim_channel", "alias": "c"} ] }]}
        # new_joins 为空 = 同源直挂；每条新 JOIN 触发对应规则的 joins/source_tables 变更许可

第一刀矩阵（add_field：冻结一切 + 新增清单）：
- 冻结：存量字段定义（类型/注释/血缘/口径）、字段删除、规则集与规则一切属性
  （除落位规则的白名单槽位）、表结构属性、meta（除派生计数与声明的新源表）、
  data_flow（除声明新表节点）、init、dq_rules（DQ 声明位 change.dq 预留，第一刀未接）。
- 许可：声明字段在（目标表 ∪ 中间表）的 fields 新增；落位规则的 field_targets 增加声明
  字段、field_logics 为声明字段补口径、join_safety 为声明的新 JOIN 补条目、
  joins/source_tables 增加声明的新 JOIN。

判定笨标准：不做语义等价推断，结构不等即差异。纯函数可测；main 只做 IO。
"""
import argparse
import json
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional, Tuple

# ts.change 段支持的动作类型（第一刀仅 add_field；矩阵扩展即此枚举扩展，原则6）
SUPPORTED_CHANGE_TYPES = {"add_field"}

# 落位规则允许变化的槽位（除白名单外的一切 aspect 差异 = 越界）
# fields 桶（两视图结构）替代 field_logics：桶内容只许为声明字段补 processed 条目
RULE_MUTABLE_SLOTS = {"field_targets", "joins", "join_safety", "fields", "source_tables"}


# ---------------------------------------------------------------------------
# diff 分解：ts_baseline vs ts_v2 → 结构化变更项
# ---------------------------------------------------------------------------

def _diff_rule(b_code: str, b_rule: dict, v_rule: dict) -> List[Tuple[str, object, object]]:
    """单规则差异 [(aspect, old, new)]。"""
    out = []
    for key in sorted(set(b_rule) | set(v_rule)):
        if b_rule.get(key) != v_rule.get(key):
            out.append((key, b_rule.get(key), v_rule.get(key)))
    return out


def decompose_diff(baseline: dict, v2: dict) -> dict:
    """diff 分解为变更项集合（不做许可判断）。"""
    b_tables, v_tables = baseline.get("tables", {}), v2.get("tables", {})
    b_rules, v_rules = baseline.get("rules", {}), v2.get("rules", {})

    added_fields, removed_fields, modified_fields = [], [], []
    for t in sorted(set(b_tables) | set(v_tables)):
        if t not in b_tables:
            added_fields.extend((t, f["target_field"]) for f in v_tables[t].get("fields", []))
            continue
        if t not in v_tables:
            removed_fields.extend((t, f["target_field"]) for f in b_tables[t].get("fields", []))
            continue
        bf = {f["target_field"]: f for f in b_tables[t].get("fields", [])}
        vf = {f["target_field"]: f for f in v_tables[t].get("fields", [])}
        for fname in sorted(set(bf) | set(vf)):
            if fname not in bf:
                added_fields.append((t, fname))
            elif fname not in vf:
                removed_fields.append((t, fname))
            elif bf[fname] != vf[fname]:
                modified_fields.append((t, fname))

    table_changes = []
    for t in sorted(set(b_tables) & set(v_tables)):
        b_meta = {k: v for k, v in b_tables[t].items() if k != "fields"}
        v_meta = {k: v for k, v in v_tables[t].items() if k != "fields"}
        if b_meta != v_meta:
            table_changes.append(t)

    rule_changes = {}
    for code in sorted(set(b_rules) | set(v_rules)):
        if code not in b_rules:
            rule_changes[code] = "added"
        elif code not in v_rules:
            rule_changes[code] = "removed"
        else:
            d = _diff_rule(code, b_rules[code], v_rules[code])
            if d:
                rule_changes[code] = d

    b_meta, v_meta = baseline.get("meta", {}), v2.get("meta", {})
    meta_changes = [k for k in sorted(set(b_meta) | set(v_meta))
                    if k not in ("field_count",) and b_meta.get(k) != v_meta.get(k)]
    df_b, df_v = baseline.get("data_flow", {}), v2.get("data_flow", {})
    data_flow_changes = [k for k in sorted(set(df_b) | set(df_v)) if df_b.get(k) != df_v.get(k)]
    dq_added = [d for d in (v2.get("dq_rules") or []) if d not in (baseline.get("dq_rules") or [])]
    init_changed = baseline.get("init", {}) != v2.get("init", {})

    return {"added_fields": added_fields, "removed_fields": removed_fields,
            "modified_fields": modified_fields, "table_changes": table_changes,
            "added_tables": [t for t in v_tables if t not in b_tables],
            "removed_tables": [t for t in b_tables if t not in v_tables],
            "rule_changes": rule_changes, "meta_changes": meta_changes,
            "data_flow_changes": data_flow_changes, "dq_added": dq_added,
            "init_changed": init_changed}


# ---------------------------------------------------------------------------
# 许可判断（add_field 矩阵）
# ---------------------------------------------------------------------------

def _declaration_index(change: dict) -> dict:
    """change 段 → 许可索引：{(表, 字段): 声明} / {rule: 声明集合} /
    {(表, 字段): 类型修改声明}（场景 B·2026-10-22）。"""
    idx = {"fields": {}, "rules": {}, "modify": {}}
    for f in change.get("fields", []):
        key = (f.get("target_table", ""), f["field"])
        idx["fields"][key] = f
        for r in f.get("placed_rules", []):
            idx["rules"].setdefault(r, []).append(f)
        for t in f.get("intermediate_tables", []):
            idx["fields"][(t, f["field"])] = f
    for m in change.get("modify_types", []):
        idx["modify"][(m.get("target_table", ""), m.get("field", ""))] = m
    return idx


def check_add_field(baseline: dict, v2: dict, change_request: dict) -> List[dict]:
    """add_field 矩阵比对。返回违规清单（空=通过）。"""
    violations: List[dict] = []
    diff = decompose_diff(baseline, v2)
    change = v2.get("change") or {}
    idx = _declaration_index(change)

    def over(msg):
        violations.append({"type": "overreach", "message": msg})

    def missing(msg):
        violations.append({"type": "missing", "message": msg})

    # ---- 正向：冻结层逐项 ----
    for t, fname in diff["added_fields"]:
        if (t, fname) not in idx["fields"]:
            over(f"[围栏][字段] 新增字段 {t}.{fname} 未在 change 段声明——越界")
    for t, fname in diff["removed_fields"]:
        over(f"[围栏][字段] 删除存量字段 {t}.{fname}——add_field 不允许删字段")
    # 场景 B（2026-10-22）：类型修改恰好性——声明的 (表,字段) 允许 field_type 变且
    # 必须恰好变为声明的新类型（types_compatible 归一比）；注释等其他键变仍冻结；
    # 未声明的存量字段定义修改照拦
    from type_compat import types_compatible
    for t, fname in diff["modified_fields"]:
        mdecl = idx["modify"].get((t, fname))
        if mdecl is None:
            over(f"[围栏][字段] 存量字段定义被修改 {t}.{fname}——存量冻结（含类型/注释/血缘/口径；"
                 f"类型修改走变更记录 MODIFY·目标字段类型申报）")
            continue
        bf = {x["target_field"]: x for x in baseline.get("tables", {}).get(t, {}).get("fields", [])}
        vf = {x["target_field"]: x for x in v2.get("tables", {}).get(t, {}).get("fields", [])}
        changed_keys = sorted(k for k in set(bf.get(fname, {})) | set(vf.get(fname, {}))
                              if bf.get(fname, {}).get(k) != vf.get(fname, {}).get(k))
        bad_keys = [k for k in changed_keys if k != "field_type"]
        if bad_keys:
            over(f"[围栏][字段] {t}.{fname} 类型修改声明下非类型键也被改 {bad_keys}——冻结")
        new_ty = (vf.get(fname) or {}).get("field_type", "")
        if not types_compatible(new_ty, mdecl.get("new_type", "")):
            over(f"[围栏][字段] {t}.{fname} 落地类型 {new_ty!r} ≠ 声明新类型 "
                 f"{mdecl.get('new_type')!r}（归一比较）——恰好性")
    # 声明了 modify 但 diff 无落点（漏改=missing）
    _modified_pairs = set(diff["modified_fields"])
    for key, m in idx["modify"].items():
        if key not in _modified_pairs:
            missing(f"[围栏][字段] modify_types 声明 {key[0]}.{key[1]} 在 diff 中无落点"
                    f"——tables 类型未更新（漏改）")
    for t in diff["added_tables"]:
        over(f"[围栏][表] 新增表 {t}——add_field 不允许加表")
    for t in diff["removed_tables"]:
        over(f"[围栏][表] 删除表 {t}——add_field 不允许删表")
    for t in diff["table_changes"]:
        over(f"[围栏][表] 表属性被修改 {t}（分布键/分区/类型等）——冻结")

    for code, d in diff["rule_changes"].items():
        if d in ("added", "removed"):
            over(f"[围栏][规则] 规则被{'新增' if d == 'added' else '删除'} {code}——add_field 不允许动规则集")
            continue
        declared = idx["rules"].get(code, [])
        declared_fields = {f["field"] for f in declared}
        new_joins = {(j["table"], j.get("alias", "")) for f in declared for j in f.get("new_joins", [])
                     if j.get("rule") == code}
        for aspect, old, new in d:
            if aspect not in RULE_MUTABLE_SLOTS:
                over(f"[围栏][规则] {code}.{aspect} 被修改——非落位白名单槽位，冻结")
                continue
            if aspect == "field_targets":
                added = set(new or []) - set(old or [])
                bad = added - declared_fields
                if bad:
                    over(f"[围栏][规则] {code}.field_targets 增加了未声明字段 {sorted(bad)}")
                removed = set(old or []) - set(new or [])
                if removed:
                    over(f"[围栏][规则] {code}.field_targets 丢失存量字段 {sorted(removed)}")
            elif aspect == "fields":
                # 两视图桶：只许为声明字段新增 processed/assign/direct 条目，存量条目冻结；
                # 口径修改声明（modify_logics·第三刀）的字段：logic 许变（恰好性——
                # 新口径不比对内容，内容锚=design_logic+闸口①'人审）且桶归属许迁
                # （direct→processed 是口径修改的合法形态——直取变加工）
                _declared_mlogics = {str(m.get("field", "")).lower()
                                     for m in change.get("modify_logics", [])}
                def _bucket_index(b):
                    out = {}
                    for kind in ("processed", "assign", "direct"):
                        for e in (b or {}).get(kind, []):
                            if isinstance(e, dict):
                                t = e.get("target")
                            elif kind == "direct":
                                # direct 串 "alias.col AS target" 身份=AS 后段（第三刀补：
                                # 此前字符串条目不进索引，direct 删改围栏看不见——盲区）
                                t = str(e).rsplit(" AS ", 1)[-1].strip() if " AS " in str(e) else None
                            else:
                                t = None
                            if t:
                                out.setdefault(t, set()).add(kind)
                    return out
                old_ix, new_ix = _bucket_index(old), _bucket_index(new)
                bad = set(new_ix) - set(old_ix) - declared_fields
                if bad:
                    over(f"[围栏][规则] {code}.fields 增加了未声明字段的条目 {sorted(bad)}")
                gone = set(old_ix) - set(new_ix)
                if gone:
                    # direct→processed 迁移会让 direct 侧消失 processed 侧出现——
                    # 桶归属比对（下一循环）覆盖；这里只拦"整字段条目消失"
                    _migrated = {t for t in gone if t in _declared_mlogics and t in new_ix}
                    real_gone = gone - _migrated
                    if real_gone:
                        over(f"[围栏][规则] {code}.fields 丢失存量字段条目 {sorted(real_gone)}")
                for t in set(old_ix) & set(new_ix):
                    if old_ix[t] != new_ix[t]:
                        if t.lower() not in _declared_mlogics:
                            over(f"[围栏][规则] {code}.fields.{t} 桶归属被改 {old_ix[t]}→{new_ix[t]}"
                                 f"（口径修改走 modify_logics 声明）")
                # 老字段 processed 条目的 logic 内容冻结（声明字段豁免——第三刀恰好性：
                # 未声明的口径被改=越界，这里正是口径修改的 ts 级守门）
                def _logic_map(b):
                    return {str(e.get("target", "")).lower(): str(e.get("logic") or "")
                            for e in (b or {}).get("processed", []) if isinstance(e, dict)}
                old_lg, new_lg = _logic_map(old), _logic_map(new)
                for t in set(old_lg) & set(new_lg):
                    if old_lg[t] != new_lg[t] and t not in _declared_mlogics:
                        over(f"[围栏][规则] {code}.fields.{t} 的口径（logic）被修改——"
                             f"存量口径冻结（口径修改走变更记录 MODIFY·映射表达式申报）")
            elif aspect == "joins":
                # ts 规则 joins 以别名为身份（表归属由 source_tables 承载）
                old_al = {j.get("alias", "") for j in (old or [])}
                new_al = {j.get("alias", "") for j in (new or [])}
                declared_al = {j.get("alias", "") for f in declared
                               for j in f.get("new_joins", []) if j.get("rule") == code}
                bad = new_al - old_al - declared_al
                if bad:
                    over(f"[围栏][规则] {code}.joins 增加了未声明的新 JOIN 别名 {sorted(bad)}")
                gone = old_al - new_al
                if gone:
                    over(f"[围栏][规则] {code}.joins 丢失存量 JOIN 别名 {sorted(gone)}")
            elif aspect == "source_tables":
                added = {(s.get("table", ""), s.get("alias", "")) for s in (new or [])} - \
                        {(s.get("table", ""), s.get("alias", "")) for s in (old or [])}
                bad = added - new_joins
                if bad:
                    over(f"[围栏][规则] {code}.source_tables 增加了未声明的新源表 {sorted(bad)}")
                gone = {(s.get("table", ""), s.get("alias", "")) for s in (old or [])} - \
                       {(s.get("table", ""), s.get("alias", "")) for s in (new or [])}
                if gone:
                    over(f"[围栏][规则] {code}.source_tables 丢失存量源表 {sorted(gone)}")

    for k in diff["meta_changes"]:
        if k == "source_tables":
            old_t = {s["table"] for s in baseline["meta"]["source_tables"]}
            new_t = {s["table"] for s in v2["meta"]["source_tables"]}
            declared_t = {j["table"] for f in change.get("fields", []) for j in f.get("new_joins", [])}
            bad = new_t - old_t - declared_t
            if bad:
                over(f"[围栏][meta] source_tables 增加了未声明源表 {sorted(bad)}")
            gone = old_t - new_t
            if gone:
                over(f"[围栏][meta] source_tables 丢失存量源表 {sorted(gone)}")
        else:
            over(f"[围栏][meta] meta.{k} 被修改——冻结")
    df_b, df_v = baseline.get("data_flow", {}), v2.get("data_flow", {})
    declared_df_nodes = {j["table"] for f in change.get("fields", []) for j in f.get("new_joins", [])}
    if "tables" in diff["data_flow_changes"]:
        b_nodes = {n["name"]: n for n in df_b.get("tables", [])}
        v_nodes = {n["name"]: n for n in df_v.get("tables", [])}
        bad = set(v_nodes) - set(b_nodes) - declared_df_nodes
        if bad:
            over(f"[围栏][data_flow] 表节点新增未声明源表 {sorted(bad)}——冻结")
        gone = set(b_nodes) - set(v_nodes)
        if gone:
            over(f"[围栏][data_flow] 表节点丢失 {sorted(gone)}——冻结")
        for n in set(b_nodes) & set(v_nodes):
            if b_nodes[n] != v_nodes[n]:
                over(f"[围栏][data_flow] 表节点 {n} 属性被修改——冻结")
    for k in diff["data_flow_changes"]:
        if k != "tables":
            over(f"[围栏][data_flow] data_flow.{k} 被修改——冻结")
    for d in diff["dq_added"]:
        over(f"[围栏][DQ] 新增 DQ 规则 {d.get('rule_name', '?')}——DQ 变更声明位（change.dq）"
             f"预留，第一刀未接（见 03 挂账）")
    if diff["init_changed"]:
        over("[围栏][init] init 段被修改——add_field 默认冻结（回刷走闸口①'人选拿后另行声明）")

    # ---- 反向：声明的每条必须有落点 ----
    cr_fields = {f["field"] for f in change_request.get("fields", [])}
    declared = change.get("fields", [])
    declared_mods = change.get("modify_types", [])
    declared_mlogics = change.get("modify_logics", [])
    if not declared and not declared_mods and not declared_mlogics:
        missing("[围栏][声明] change 段为空——ts_v2 缺设计落位声明")
    for f in declared:
        fname = f["field"]
        if fname not in cr_fields:
            over(f"[围栏][声明] change 声明的字段 {fname!r} 不在 change_request（设计夹带）")
        tgt = f.get("target_table", "")
        v_fields = {x["target_field"] for x in v2.get("tables", {}).get(tgt, {}).get("fields", [])}
        if fname not in v_fields:
            missing(f"[围栏][声明] {fname} 声明了但目标表 {tgt} 没有该字段——漏改")
        for r in f.get("placed_rules", []):
            r_rule = v2.get("rules", {}).get(r)
            if r_rule is None:
                missing(f"[围栏][声明] {fname} 落位规则 {r} 不存在——漏改")
            elif fname not in (r_rule.get("field_targets") or []):
                missing(f"[围栏][声明] {fname} 落位规则 {r} 的 field_targets 没有它——漏改")
        for t in f.get("intermediate_tables", []):
            t_fields = {x["target_field"] for x in v2.get("tables", {}).get(t, {}).get("fields", [])}
            if fname not in t_fields:
                missing(f"[围栏][声明] {fname} 声明穿中间表 {t} 但该表没有此字段——漏改")
    # change_request 每条业务声明都必须被 change 段接住（意图→落位对账）
    for f in change_request.get("fields", []):
        if f["field"] not in {d["field"] for d in declared}:
            missing(f"[围栏][声明] change_request 的 {f['field']!r} 未被 change 段落位——漏接")
    # 类型修改同款双向（场景 B）：ts.change.modify_types ↔ change_request.modify_type_fields
    cr_mods = {m["field"] for m in change_request.get("modify_type_fields", [])}
    for m in declared_mods:
        if m["field"] not in cr_mods:
            over(f"[围栏][声明] modify_types 声明的字段 {m['field']!r} 不在"
                 f" change_request（设计夹带）")
    for f in change_request.get("modify_type_fields", []):
        if f["field"] not in {m["field"] for m in declared_mods}:
            missing(f"[围栏][声明] change_request 的类型修改 {f['field']!r} 未被"
                    f" change 段接住——漏接")
    # 口径修改同款双向（第三刀）：ts.change.modify_logics ↔ cr.modify_logic_fields
    cr_mlogics = {m["field"] for m in change_request.get("modify_logic_fields", [])}
    for m in declared_mlogics:
        if m["field"] not in cr_mlogics:
            over(f"[围栏][声明] modify_logics 声明的字段 {m['field']!r} 不在"
                 f" change_request（设计夹带）")
    for f in change_request.get("modify_logic_fields", []):
        if f["field"] not in {m["field"] for m in declared_mlogics}:
            missing(f"[围栏][声明] change_request 的口径修改 {f['field']!r} 未被"
                    f" change 段接住——漏接")
    return violations


def check(baseline: dict, v2: dict, change_request: dict) -> List[dict]:
    """围栏入口：按 change_type 分发矩阵（两侧先归一到两视图结构再比，幂等）。"""
    from ts_compat import normalize_ts
    baseline, v2 = normalize_ts(baseline), normalize_ts(v2)
    ctype = (v2.get("change") or change_request).get("change_type", "")
    if ctype not in SUPPORTED_CHANGE_TYPES:
        return [{"type": "unsupported",
                 "message": f"[围栏] 不支持的 change_type {ctype!r}"
                            f"（本刀支持: {sorted(SUPPORTED_CHANGE_TYPES)}）"}]
    return check_add_field(baseline, v2, change_request)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ts 级围栏：声明驱动的冻结层比对")
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--change-request", required=True)
    args = ap.parse_args(argv)
    baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    v2 = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    cr = json.loads(Path(args.change_request).read_text(encoding="utf-8"))

    violations = check(baseline, v2, cr)
    if violations:
        over = sum(1 for v in violations if v["type"] in ("overreach", "unsupported"))
        miss = sum(1 for v in violations if v["type"] == "missing")
        print(f"FENCE_BLOCKED：越界 {over} 项 / 漏改 {miss} 项", file=sys.stderr)
        for v in violations:
            print(f"  {v['message']}", file=sys.stderr)
        return 1
    print("FENCE_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
