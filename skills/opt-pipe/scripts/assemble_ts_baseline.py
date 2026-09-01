"""assemble_ts_baseline —— baseline_v1 契约 → ts_baseline（优化场景的存量地基）。

设计依据：docs/specs/opt/02-baseline组装与接入.md。
产出四件（--outdir，一般指向 {deliver}/_internal）：
  ts_baseline.json   ts 形状的存量骨架（结构事实填充 + 语义位留空 + _baseline 标记）
  etl_baseline/      query_sql 逐字落盘（一规则一文件；围栏/双跑/coder 参照基准）
  exemptions.json    语义空位清单（格式对齐 assemble_ts 豁免 {code,target,reason}）
  baseline_view.md   designer 读的 compact 视图

组装原则（02 §四 + 契约 v1.1 精神）：
- 文法/拓扑可推导的结构事实 → 填（target_role/produces_for/reads/dependencies 等）
- 设计判断（语义位）→ 显式留空 + 豁免记录，绝不伪造（business_key/step_type/join_safety/
  grain/field_logics/distribution_key/init 管道判断）
- write_plan.kind → load_mode 映射归本侧；词表覆盖不了的 kind → load_mode 留空 +
  "写入类型待定"记录（无假信息纪律的消费端镜像）

纯函数可测（build_* 无 IO），main 只做编排与落盘。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from baseline_contract import validate_baseline_v1

# ---------------------------------------------------------------------------
# write_plan.kind → load_mode（本侧词表；kind 已由 analyzer 按平台代次翻译）
# ---------------------------------------------------------------------------
KIND_TO_LOAD_MODE = {
    "full_truncate": "truncate_table",
    "append": "no_delete",
    "delete_by_condition": "delete",
    "partition_truncate": "truncate_partition",
    "merge_upsert": "merge_into",
    "update_by_condition": "update",
}
# 词表覆盖不了的 kind：load_mode 留空 + 待定记录（不硬映射、不伪造）
PENDING_KINDS = {"subpartition_truncate", "rpt_item", "exchange_partition", "unknown"}

# kind → meta.load_strategy.strategy（展示标签：overwrite|partition|append）
KIND_TO_STRATEGY = {
    "full_truncate": "overwrite", "subpartition_truncate": "overwrite",
    "partition_truncate": "partition",
    "append": "append", "merge_upsert": "append", "update_by_condition": "append",
    "delete_by_condition": "overwrite", "rpt_item": "overwrite",
    "exchange_partition": "partition", "unknown": "overwrite", "view": "overwrite",
}

_LAYER_BY_PREFIX = (("ods", "ODS"), ("dwb", "DWB"), ("dwl", "DWL"), ("dim", "DIM"))


def _table_short(full: str) -> str:
    """schema.table → table（ts 内键用短名）。"""
    return full.split(".")[-1] if "." in full else full


def _layer_of(schema: str) -> str:
    s = (schema or "").lower()
    for prefix, layer in _LAYER_BY_PREFIX:
        if s.startswith(prefix):
            return layer
    return ""


# ---------------------------------------------------------------------------
# 拓扑推导（结构事实，非语义）
# ---------------------------------------------------------------------------

def _table_full(r: dict) -> str:
    """规则目标表全名（schema.table，N12b：target_table/reads 统一带 schema）。"""
    return f"{r['target_schema']}.{r['target_table']}"


def derive_topology(rules: List[dict]) -> Dict[str, dict]:
    """推导：每规则目标表 / 交叉读写关系 / 表角色（intermediate|target）。

    返回 {rule_code: {"target_short"/"target_full":…, "reads_tables"(全名), "produces_for": [...]}}，
    外加 "_written_tables": {表全名: 产出规则}、"_table_roles": {表全名: role}、
    "_written_short": {短名: 全名}（tables 段键为短名，按新版约定）。
    produces_for 语义与 ts 模板一致：本规则产出的表供哪些规则消费（方向：被读）。
    """
    written: Dict[str, str] = {}      # 表全名 → 产出 rule_code
    for r in rules:
        written[_table_full(r)] = r["rule_code"]

    info: Dict[str, dict] = {}
    for r in rules:
        code = r["rule_code"]
        full = _table_full(r)
        reads_tables = [t for t in r.get("source_tables", [])
                        if t in written and written[t] != code]
        info[code] = {"rule_code": code, "target_short": _table_short(full),
                      "target_full": full, "reads_tables": reads_tables, "produces_for": []}
    # 方向修正：C 读 P 的表 → P.produces_for 收 C
    for code, d in info.items():
        for t in d["reads_tables"]:
            producer = written[t]
            info[producer]["produces_for"].append(code)
    for d in info.values():
        d["produces_for"] = sorted(set(d["produces_for"]))
    # 表角色：被其他规则读 → intermediate；否则 target
    read_tables = {t for d in info.values() for t in d["reads_tables"]}
    table_roles = {t: ("intermediate" if t in read_tables else "target") for t in written}
    info["_written_tables"] = written
    info["_table_roles"] = table_roles
    info["_written_short"] = {_table_short(t): t for t in written}
    return info


# ---------------------------------------------------------------------------
# 组装 ts_baseline
# ---------------------------------------------------------------------------

def build_tables(data: dict, topo: Dict[str, dict]) -> Tuple[Dict[str, dict], List[dict]]:
    """契约 tables[] + lineage → ts.tables dict（仅规则产出的表；源表进 meta.source_tables）。"""
    written: Dict[str, str] = topo["_written_tables"]            # 全名 → rule
    written_short: Dict[str, str] = topo["_written_short"]        # 短名 → 全名
    table_roles: Dict[str, str] = topo["_table_roles"]            # 全名 → role
    contract_tables = {_table_short(t["schema"] + "." + t["name"]): t for t in data.get("tables", [])}

    # lineage 按 (rule, target_field) 索引，供字段 enrich
    lineage_by_rule: Dict[str, Dict[str, dict]] = {}
    for ln in data.get("lineage", []):
        lineage_by_rule.setdefault(ln["rule_code"], {})[ln["target_field"]] = ln

    gaps: List[dict] = []
    ts_tables: Dict[str, dict] = {}
    for short, rule_code in sorted(((s_, written[f_]) for s_, f_ in written_short.items()),
                                   key=lambda kv: kv[1]):
        ct = contract_tables.get(short, {})
        fields_def = ct.get("fields") or []
        lns = lineage_by_rule.get(rule_code, {})
        fields = []
        for f in fields_def:
            ln = lns.get(f["name"])
            fields.append({
                "target_field": f["name"],
                "field_type": f.get("type", ""),
                "field_comment": f.get("comment", ""),
                "transform_type": (ln or {}).get("transform_type", ""),
                "source_fields": [
                    {"table": ps["table"], "field": ps["field"], "alias": ""}
                    for ps in (ln or {}).get("physical_sources", [])
                ],
                "design_logic": "",   # 语义位：口径留空
            })
        # 血缘里有、DDL fields 没有的字段（如 demo 的 tmp 中间列）补骨架（type 空）
        known = {f["target_field"] for f in fields}
        for fname, ln in lns.items():
            if fname in known:
                continue
            fields.append({
                "target_field": fname, "field_type": "", "field_comment": "",
                "transform_type": ln.get("transform_type", ""),
                "source_fields": [{"table": ps["table"], "field": ps["field"], "alias": ""}
                                  for ps in ln.get("physical_sources", [])],
                "design_logic": "",
            })
        ts_tables[short] = {
            "type": table_roles[written_short[short]],
            "distribution_key": [],        # 语义位：物理决策留空
            "distribute_type": "ROUNDROBIN",
            "partition": "",
            "storage": "column",
            "logical_group": "",
            "fields": fields,
        }
        gaps.append({"code": "distribution_key", "target": short,
                     "reason": "逆向基线语义空位：分布键为物理设计决策"})
    return ts_tables, gaps


def build_rules(data: dict, topo: Dict[str, dict]) -> Tuple[Dict[str, dict], List[dict]]:
    """契约 rules[] → ts.rules dict（结构事实填充 + 语义位留空）。"""
    written = topo["_written_tables"]
    gaps: List[dict] = []
    alias_by_table: Dict[str, str] = {}
    for r in data["rules"]:
        for j in r.get("joins", []):
            alias_by_table.setdefault(j.get("source_table", ""), j.get("alias", ""))

    ts_rules: Dict[str, dict] = {}
    for r in sorted(data["rules"], key=lambda x: x["exec_sequence"]):
        code = r["rule_code"]
        info = topo[code]
        wp = r.get("write_plan")
        kind = (wp or {}).get("kind", "")
        load_mode = KIND_TO_LOAD_MODE.get(kind, "")
        if wp is None:
            # v1.0 老产物无 write_plan：不回退到本侧 dm 映射（权威在解析侧），显式缺口
            gaps.append({"code": "write_plan_missing", "target": code,
                         "reason": "v1.0 产物缺 write_plan（契约 v1.1 起提供）——"
                                   "load_mode 留空，建议用 analyzer 重导出 v1.1"})
        elif kind in PENDING_KINDS or not load_mode:
            gaps.append({"code": "load_mode_pending", "target": code,
                         "reason": f"写入类型待定：write_plan.kind={kind!r} 无对应 load_mode，"
                                   f"禁止硬映射（后续词表扩展或人工认定）"})
        # 源表拆分：外部表 → source_tables；本资产中间表 → reads
        src, reads = [], []
        for full in r.get("source_tables", []):
            if full in written and written[full] != code:   # 本资产中间表（全名键）
                reads.append(full)
            else:
                src.append({"schema": full.split(".")[0] if "." in full else "",
                            "table": _table_short(full), "alias": alias_by_table.get(full, "")})
        joins = [{"alias": j.get("alias", ""), "type": j.get("join_type", ""),
                  "condition": j.get("join_condition", ""), "filter": ""}
                 for j in r.get("joins", [])]
        ts_rules[code] = {
            "rule_name": r.get("rule_name", ""),
            "scenario": r.get("scenario_id", ""),
            "exec_sequence": r["exec_sequence"],
            "target_table": info["target_full"],   # 带 schema（N12b；tables 键仍短名）
            "is_view_step": bool(r.get("is_view_step", False)),
            "design_intent": "",                      # 语义位
            "load_mode": load_mode,
            "write_condition": (wp or {}).get("condition_expr") or "",
            "step_type": "",                          # 语义位：加工路径是设计判断
            "target_role": topo["_table_roles"][info["target_full"]],
            "produces_for": info["produces_for"],
            "reads": info["reads_tables"],   # 带 schema（N12b）
            "source_tables": src,
            "grain": {"input": "", "output": "", "change": ""},   # 语义位
            "joins": joins,
            "join_safety": [],                        # 语义位：关联安全声明
            "field_targets": sorted({ln["target_field"] for ln in data.get("lineage", [])
                                     if ln["rule_code"] == code}),
            "field_logics": {},                       # 语义位：加工口径
        }
        for slot in ("design_intent", "step_type", "grain", "field_logics"):
            gaps.append({"code": slot, "target": code, "reason": "逆向基线语义空位"})
        gaps.append({"code": "join_safety", "target": code,
                     "reason": "逆向基线语义空位：老关联以生产在跑为证，新关联由 designer 声明"})
    return ts_rules, gaps


def build_data_flow(data: dict, topo: Dict[str, dict]) -> dict:
    written = topo["_written_tables"]
    nodes = []
    for t in data.get("tables", []):
        short = t["name"]
        nodes.append({"schema": t["schema"], "name": short,
                      "role": ("target" if short in written else "source"),
                      "layer": _layer_of(t["schema"]), "is_view": False})
    deps = []
    for r in data["rules"]:
        code = r["rule_code"]
        for t in topo[code]["reads_tables"]:   # 全名（N12b）
            deps.append({"from": written[t], "to": code, "type": "data_flow",
                         "intermediate_table": t})
    groups: Dict[int, List[str]] = {}
    for r in data["rules"]:
        groups.setdefault(r["exec_sequence"], []).append(r["rule_code"])
    schedule_groups = [{"sequence": seq, "rules": sorted(codes)}
                       for seq, codes in sorted(groups.items())]
    return {"tables": nodes, "dependencies": deps, "schedule_groups": schedule_groups}


def build_ts_baseline(data: dict) -> Tuple[dict, List[dict]]:
    """契约 → (ts_baseline, 语义空位清单)。纯函数。"""
    topo = derive_topology(data["rules"])
    ts_tables, gaps1 = build_tables(data, topo)
    ts_rules, gaps2 = build_rules(data, topo)
    gaps = gaps1 + gaps2

    # 最终目标表 = 规则拓扑的终点（target 角色；视图资产取非视图目标）
    target_short = next((t for t, role in topo["_table_roles"].items() if role == "target"), "")
    target_rule = next((r for r in data["rules"] if _table_short(r["target_table"]) == target_short), {})
    wp = target_rule.get("write_plan") or {}
    target_full = f"{data['asset']['schema']}.{data['asset']['table']}"

    src_tables_meta = []
    written = topo["_written_tables"]
    for t in data.get("tables", []):
        if t["name"] not in written:
            src_tables_meta.append({"schema": t["schema"], "table": t["name"],
                                    "table_cn": "", "alias": ""})

    ts = {
        "version": "1.0.0",
        "spec_type": "ts",
        "generated_at": data["asset"].get("analysis_time", ""),
        "generated_by": "assemble_ts_baseline",
        "_baseline": {   # 逆向来源标记（本体系内消费；下游工具忽略未知键）
            "source": "baseline_v1", "contract_version": data["version"],
            "platform_generation": data["asset"].get("platform_generation", ""),
            "asset": target_full,
        },
        "meta": {
            "target": {"f_table": {"schema": data["asset"]["schema"],
                                   "table": data["asset"]["table"], "cn": ""},
                       "i_view": {"schema": "", "table": "", "cn": ""}},
            "grain": "",                       # 语义位
            "load_strategy": {"strategy": KIND_TO_STRATEGY.get(wp.get("kind", ""), ""),
                              "label": wp.get("kind", ""),
                              "delete_mode": target_rule.get("delete_mode", "")},
            "field_count": {
                "business": len(ts_tables.get(target_short, {}).get("fields", [])),
                "audit": 0, "total": len(ts_tables.get(target_short, {}).get("fields", [])),
            },
            "source_tables": src_tables_meta,
            "schedule": {},                    # 调度对比走契约层（baseline_view 呈现），不进 ts
        },
        "design": {"complexity_analysis": {}, "audit_fields": {}, "business_key": []},
        "tables": ts_tables,
        "rules": ts_rules,
        "data_flow": build_data_flow(data, topo),
        "init": {"mode": "", "group_mode": "", "rules": {}},
        "dq_rules": [
            {"scope": "", "check_type": d.get("check_type", ""),
             "rule_name": d.get("rule_name", ""), "rule_desc": d.get("rule_desc", "")}
            for d in (data.get("dq_rules") or [])
        ],
    }
    gaps.append({"code": "business_key", "target": target_short,
                 "reason": "逆向基线语义空位：主键是人给的（存量回归由输出对比保障）"})
    gaps.append({"code": "init_section", "target": data["asset"]["table"],
                 "reason": "逆向基线语义空位：init/增量双管道判断是设计语义（增量人选拿回刷时建立）"})
    return ts, gaps


# ---------------------------------------------------------------------------
# baseline_view（designer 读的 compact 视图，从契约直接渲染）
# ---------------------------------------------------------------------------

def render_baseline_view(data: dict, ts: dict, gaps: List[dict]) -> str:
    asset = data["asset"]
    lines: List[str] = []
    lines.append(f"# baseline_view · {asset['schema']}.{asset['table']}")
    lines.append("")
    lines.append(f"> 逆向基线（契约 v{data['version']}，platform_generation="
                 f"{asset.get('platform_generation', '')}，{asset.get('analysis_time', '')}）。"
                 f"提示：load_strategy / patterns 为非权威 hint；warnings 是逆向置信度。")
    lines.append("")
    lines.append("## 规则清单")
    lines.append("| 规则 | 目标表 | 写入类型(kind) | load_mode | 写入条件 | 源表/中间表 | 场景 |")
    lines.append("|------|--------|----------------|-----------|----------|------------|------|")
    pending_rules = [g["target"] for g in gaps if g["code"] == "load_mode_pending"]
    kind_by_rule = {r["rule_code"]: (r.get("write_plan") or {}).get("kind", "?")
                    for r in data["rules"]}
    for code, r in ts["rules"].items():
        flag = " ⚠️待定" if code in pending_rules else ""
        srcs = ",".join(f"{s['table']}" for s in r["source_tables"])
        reads = ",".join(r["reads"])
        src_cell = srcs + ((" | 读中间表: " + reads) if reads else "") if (srcs or reads) else "-"
        lines.append(f"| {code} | {r['target_table']} | {kind_by_rule.get(code, '?')}{flag} | "
                     f"{r['load_mode'] or '待定'} | {r['write_condition'] or '-'} | "
                     f"{src_cell} | {r['scenario']} |")
    lines.append("")
    lines.append("## 增量材料（write_plan / 调度参数，designer 判断增量语义用）")
    for r in data["rules"]:
        wp = r.get("write_plan") or {}
        lines.append(f"- {r['rule_code']}: kind={wp.get('kind', '?')} "
                     f"role={wp.get('condition_role', '?')} "
                     f"cond={wp.get('condition_expr') or '-'} "
                     f"cols={wp.get('condition_columns') or []} "
                     f"src={wp.get('condition_source', '?')}；"
                     f"where={r.get('where_clause') or '-'}")
    lines.append("")
    lines.append("## 字段血缘摘要（目标表）")
    target_short = ts["meta"]["target"]["f_table"]["table"]
    for f in ts["tables"].get(target_short, {}).get("fields", []):
        src = ",".join(f"{s['table']}.{s['field']}" for s in f["source_fields"]) or "-"
        lines.append(f"- {f['target_field']}（{f['field_type'] or '类型待回填'}）"
                     f" ← {src} [{f['transform_type'] or '?'}]")
    lines.append("")
    ls = data.get("load_strategy") or {}
    if ls:
        lines.append(f"## hint（非权威）\n- load_strategy: {ls.get('label', '')}（{ls.get('detail', '')}）")
    for p in data.get("patterns") or []:
        lines.append(f"- pattern: {p.get('label', '')} — {p.get('detail', '')}")
    warns = data.get("warnings") or []
    if warns:
        lines.append("")
        lines.append(f"## warnings（逆向置信度，{len(warns)} 条，资产健康提示用）")
        for w in warns:
            lines.append(f"- [{w.get('severity', '?')}] {w.get('title', '')}")
    lines.append("")
    sem = [g for g in gaps if g["code"] != "load_mode_pending"]
    pend = [g for g in gaps if g["code"] == "load_mode_pending"]
    lines.append(f"## 语义空位（{len(sem)} 条，优化模式只对增量部分建立）")
    lines.append("存量的主键/粒度/关联安全/口径/分布键均未声明——按设计原则不需要补；"
                 "新字段相关的新 JOIN 由 designer 现声明。")
    if pend:
        lines.append("")
        lines.append(f"## ⚠️ 写入类型待定（{len(pend)} 条，禁止硬映射，需人工认定）")
        for g in pend:
            lines.append(f"- {g['target']}: {g['reason']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="baseline_v1 → ts_baseline 基线包组装")
    ap.add_argument("--baseline", required=True, help="baseline_v1.json 路径")
    ap.add_argument("--outdir", required=True, help="输出目录（{deliver}/_internal）")
    args = ap.parse_args(argv)

    data = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    violations = validate_baseline_v1(data)
    if violations:
        print("[BASELINE_CONTRACT_VIOLATION] 契约校验不通过，拒绝组装：", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 2

    ts, gaps = build_ts_baseline(data)
    view = render_baseline_view(data, ts, gaps)

    outdir = Path(args.outdir)
    (outdir / "etl_baseline").mkdir(parents=True, exist_ok=True)
    (outdir / "ts_baseline.json").write_text(
        json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "exemptions.json").write_text(
        json.dumps({"_reverse_engineered": True, "items": gaps},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "baseline_view.md").write_text(view, encoding="utf-8")
    # query_sql 逐字落盘（不做任何变换）
    for r in data["rules"]:
        (outdir / "etl_baseline" / f"{r['rule_code']}.sql").write_text(
            r["query_sql"], encoding="utf-8")

    print(f"ts_baseline: {outdir / 'ts_baseline.json'}")
    print(f"rules: {len(ts['rules'])}, semantic_gaps: {len(gaps)}, "
          f"pending_load_mode: {sum(1 for g in gaps if g['code'] == 'load_mode_pending')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
