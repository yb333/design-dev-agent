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
import re
import shutil
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
        # 物理属性回收（2026-10-27 批0-①：契约 table_props 本就为「档案 DDL 走 ts
        # 投影无损再生」设计——此前留空+硬编码 ROUNDROBIN=投影断损+丢信息，gap 还
        # 错定性为"语义空位"〔物理事实非判断位〕。is_distribute_key 字段级权威与
        # distribute_columns 的一致性归逆向自检域）
        props = ct.get("table_props") or {}
        dist_key = [f["name"] for f in fields_def if f.get("is_distribute_key")]
        by = str(props.get("distribute_by") or "").strip()
        dist_type = (re.split(r"[\s(]+", by, 1)[0].upper() if by
                     else ("HASH" if dist_key else "ROUNDROBIN"))
        ts_tables[short] = {
            "type": table_roles[written_short[short]],
            "distribution_key": dist_key,
            "distribute_type": dist_type,
            "partition": str(props.get("partition_by") or ""),
            "storage": "column",
            "logical_group": "",
            "fields": fields,
        }
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
            # 原始制品定位（xlsx/代码仓路径清单）——artifact_patcher --source 从这读
            "provenance": data.get("provenance") or [],
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
    """逆向入料版 baseline_view（decisions 语言地图，2026-10-23 批1 重写）。

    与档案路径（preprocess_opt.render_baseline_view_from_ts）共用 decisions 语言核心段
    （锚点/规则拓扑/别名对照——同单元 import，单实现）；本版追加逆向特有的置信度材料
    （增量材料 write_plan / hint / warnings / 语义空位 / 写入类型待定）。逐字段血缘摘要
    不再渲染（territory——变更涉及字段的存量条目由 preprocess_opt 内联进 change_request）。"""
    from preprocess_opt import build_alias_map, render_topology_sections

    asset = data["asset"]
    lines = []
    lines.append(f"# baseline_view · {asset['schema']}.{asset['table']}")
    lines.append("")
    lines.append(f"> 逆向基线（契约 v{data['version']}，platform_generation="
                 f"{asset.get('platform_generation', '')}，{asset.get('analysis_time', '')}）。"
                 "结构=从制品同构映射；判断位（粒度/主键/join_safety/口径理解）制品里没有——"
                 "▢ 空位，只为增量建立语义。load_strategy / patterns 为非权威 hint；"
                 "warnings 是逆向置信度。")
    lines.append("")
    sql_by_rule = {r["rule_code"]: (r.get("query_sql") or "") for r in data["rules"]}
    lines += render_topology_sections(ts, build_alias_map(sql_by_rule, ts))
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
    lines.append("## 目标表字段数")
    lines.append("")
    for tb, td in sorted((ts.get("tables") or {}).items()):
        lines.append(f"- {tb}: {len(td.get('fields') or [])} 字段")
    ls = data.get("load_strategy") or {}
    if ls:
        lines.append("")
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
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def copy_artifacts_from_provenance(data: dict, archive_dir: Path) -> List[str]:
    """按产物 provenance[] 拷原始制品入 archive/export/（patch 底本，保原文件名）。

    facts 模式（无 manifest 文件）的拷贝通道：provenance 逐条 {type, path[, sheets]}——
    拷 execution_tasks / lts / dq（excel 制品；.sql DDL 不拷=档案 ddl/ 由 ts 投影）。
    缺 path/文件不存在 → 报告行披露（不阻断）。"""
    import shutil as _sh
    report: List[str] = []
    export = archive_dir / "export"
    export.mkdir(parents=True, exist_ok=True)
    for pv in (data.get("provenance") or []):
        ptype = str(pv.get("type") or "")
        path = str(pv.get("path") or "")
        if ptype not in ("execution_tasks", "lts", "dq") or not path:
            continue
        src = Path(path)
        if not src.exists():
            report.append(f"export/ 跳过 {ptype}: 源文件不存在 {path}（披露——patch 时问人）")
            continue
        _sh.copy2(src, export / src.name)
        report.append(f"export/ <- {ptype}: {src.name}")
    return report


def copy_artifacts_to_export(manifest_path: Path, archive_dir: Path) -> List[str]:
    """按 manifest 的 artifacts 清单拷原始制品入 archive/export/（patch 底本，保留原文件名）。

    2026-10-14 编排合入补全：首优制品经手一次入档（幂等全图）；DDL 原始文件不拷
    （档案 ddl/ 由 ts 投影生成）。返回拷贝报告行（stdout 披露）；manifest 缺失/无
    artifacts 段 → 空报告（直交通道场景，跳过不阻断）。
    """
    report: List[str] = []
    if not manifest_path or not manifest_path.exists():
        return report
    mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    arts = mf.get("artifacts") or {}
    export = archive_dir / "export"
    export.mkdir(parents=True, exist_ok=True)
    for key in ("execution_tasks", "lts"):
        p = arts.get(key)
        if p and Path(p).exists():
            shutil.copy2(p, export / Path(p).name)
            report.append(f"export/ <- {key}: {Path(p).name}")
    dq = arts.get("dq") or {}
    if dq.get("status") == "provided":
        p = dq.get("path")
        if p and Path(p).exists():
            shutil.copy2(p, export / Path(p).name)
            report.append(f"export/ <- dq: {Path(p).name}")
    # declared_absent / 缺省：无文件可拷（"无 DQ"声明已由 baseline_v1.dq_rules=[] 携带）
    return report


def _archive_ts_draft(draft: dict, args) -> int:
    """v2 ts 草稿建档：契约进门验（我方权威 schema v2.1）+ 资产对账 + 守门 + **copy**。

    - ts.json = 草稿**逐字落档**（_reverse 段随档——档案单文件自足；消费端围栏/UT/
      切片天然忽略下划线段）；etl/{rule}.sql = rules[].query_sql 逐字（coder 底稿/
      SQL 围栏基准）；export/ = _baseline.provenance 拷制品（同 v1 通道）；MANIFEST
      首条 v2。无 exemptions/build_ts_baseline——草稿即档形态，装配北移逆向侧。
    """
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas"
                         / "ts_draft_v2.schema.json").read_text(encoding="utf-8"))
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(draft),
                  key=lambda e: list(e.path))
    if errs:
        print("[TS_DRAFT_CONTRACT_VIOLATION] v2 契约进门验不通过，拒绝建档：", file=sys.stderr)
        for e in errs:
            print(f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}", file=sys.stderr)
        return 2
    f_table = (draft.get("meta", {}).get("target", {}) or {}).get("f_table", {}) or {}
    if args.asset:
        from baseline_contract import norm_asset
        _got = f"{f_table.get('schema', '')}.{f_table.get('table', '')}"
        if norm_asset(_got) != norm_asset(args.asset):
            print(f"[TS_DRAFT_CONTRACT_VIOLATION] 资产对账不通过：产物 {_got!r} ≠ 本次 {args.asset!r}",
                  file=sys.stderr)
            return 2
    archive, internal = Path(args.archive_dir), Path(args.internal_dir)
    if (archive / "ts.json").exists():
        print(f"[BASELINE_CONTRACT_VIOLATION] 拒绝建档：{archive} 已是确认档案——覆盖重入料=线上被外力"
              "改过/推倒重来（人发起的重建），本脚本不自动覆盖", file=sys.stderr)
        return 2
    (archive / "etl").mkdir(parents=True, exist_ok=True)
    internal.mkdir(parents=True, exist_ok=True)
    prov = (draft.get("_baseline") or {}).get("provenance") or []
    if prov:
        for line in copy_artifacts_from_provenance({"provenance": prov}, archive):
            print(line)
    (archive / "MANIFEST.md").write_text(
        f"# 资产演进索引 · {f_table.get('schema','')}.{f_table.get('table','')}\n\n"
        "（当前态 = archive/ 本体；此文件为版本史一眼索引，完整历史在 git）\n\n"
        "| 版本 | 内容 |\n|------|------|\n"
        "| v1 | 逆向入料建档（ts 草稿 v2 契约 → 审核确认后逐字落档，经 audit_ingest）|\n",
        encoding="utf-8")
    (archive / "ts.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for code, r in sorted((draft.get("rules") or {}).items()):
        (archive / "etl" / f"{code}.sql").write_text(str(r.get("query_sql") or ""),
                                                     encoding="utf-8")
    from preprocess_opt import render_baseline_view_from_ts
    (internal / "baseline_view.md").write_text(
        render_baseline_view_from_ts(draft), encoding="utf-8")
    sc = (draft.get("_reverse") or {}).get("self_check") or {}
    print(f"archive ts: {archive / 'ts.json'}（v2 草稿逐字落档，零解析）")
    print(f"rules: {len(draft.get('rules') or {})}，etl 逐字落盘；"
          f"self_check={sc.get('verdict', '?')}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="baseline_v1 入料建档（档案件落 archive/，过程件落 opt/_internal/）")
    ap.add_argument("--baseline", required=True, help="资产事实包 json 路径（原 baseline_v1.json，更名随契约波次）")
    ap.add_argument("--archive-dir", required=True, help="档案目录（ddlc_design_dev/archive/）")
    ap.add_argument("--internal-dir", required=True, help="过程目录（ddlc_design_dev/opt/_internal/）")
    ap.add_argument("--manifest", default=None, help="逆向侧的制品清单文件（可选：给则按清单拷原始制品入 archive/export/）")
    ap.add_argument("--asset", default="", help="资产对账（schema.table，probe 推出——与产物 asset 段比对，不一致=串包拒收；缺省跳过）")
    args = ap.parse_args(argv)

    data = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    # v2 ts 草稿建档（2026-10-28 批3：契约=最终形态——审核过后的建档动作=守门+copy，
    # 零解析零变换[任何需要的变换留在消费侧=契约失败]；v1 facts 路径保留=双支持期）
    if data.get("spec_type") == "ts" and str(data.get("version", "")).startswith("2."):
        return _archive_ts_draft(data, args)

    violations = validate_baseline_v1(data)
    # 资产对账（验收链独立一侧：我们从变更输入推资产，逆向从制品解析资产——双侧独立互证防串包）
    if args.asset:
        from baseline_contract import norm_asset
        _got = ((data.get("asset") or {}).get("schema", "")
                + "." + (data.get("asset") or {}).get("table", ""))
        if norm_asset(_got) != norm_asset(args.asset):
            print(f"[BASELINE_CONTRACT_VIOLATION] 资产对账不通过，拒绝组装：", file=sys.stderr)
            print(f"  产物资产 = {_got!r}，本次资产 = {args.asset!r}"
                  f"（I/F 镜像归一后仍不一致=串包：制品不是这个资产的）", file=sys.stderr)
            return 2
    if violations:
        print("[BASELINE_CONTRACT_VIOLATION] 契约校验不通过，拒绝组装：", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 2

    ts, gaps = build_ts_baseline(data)
    view = render_baseline_view(data, ts, gaps)

    archive, internal = Path(args.archive_dir), Path(args.internal_dir)
    # 建档守门（交付门模型 2026-10-14）：archive/ 存在性=确认性——本脚本只允许无档建档；
    # 已有档（ts.json 在）= 确认档，覆盖=「线上被外力改过」语义，人显式决策后才动
    if (archive / "ts.json").exists():
        print(f"[BASELINE_CONTRACT_VIOLATION] 拒绝建档：{archive} 已是确认档案——", file=sys.stderr)
        print("  覆盖重入料 = 线上被外力改过/推倒重来（人发起的重建），处置由人定，", file=sys.stderr)
        print("  本脚本不自动覆盖（人确认后手工清理档案再调）", file=sys.stderr)
        return 2
    (archive / "etl").mkdir(parents=True, exist_ok=True)
    internal.mkdir(parents=True, exist_ok=True)
    if args.manifest:
        for line in copy_artifacts_to_export(Path(args.manifest), archive):
            print(line)
    else:
        for line in copy_artifacts_from_provenance(data, archive):
            print(line)
    # asset_facts 原文随档（出生证明：基线从哪份制品逆向来的——溯源与「逆向一次」对齐）
    facts_src = Path(args.baseline)
    if facts_src.exists():
        import shutil as _sh
        _sh.copy2(facts_src, archive / "asset_facts.json")
        print("asset_facts: 随档留存（出生证明）")
    # MANIFEST 首建——首条=正经交付条目（确立基线=交付了基线；出身标记：逆向入料 vs new-pipe 建造）
    f = ts.get("meta", {}).get("target", {}).get("f_table", {})
    (archive / "MANIFEST.md").write_text(
        f"# 资产演进索引 · {f.get('schema','')}.{f.get('table','')}\n\n"
        "（当前态 = archive/ 本体；此文件为版本史一眼索引，完整历史在 git）\n\n"
        "| 版本 | 内容 |\n|------|------|\n"
        "| v1 | 逆向入料建档（asset_facts → ts_baseline，经入料审核确认）|\n",
        encoding="utf-8")
    print("MANIFEST: 首建（v1 逆向入料建档——经审核确认）")
    # 档案件（资产当前态；provenance 保留原始制品定位——artifact_patcher --source 的来源）
    (archive / "ts.json").write_text(
        json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    # query_sql 逐字落盘（不做任何变换）
    for r in data["rules"]:
        (archive / "etl" / f"{r['rule_code']}.sql").write_text(
            r["query_sql"], encoding="utf-8")
    # 过程件（designer 读 + 豁免清单）
    (internal / "exemptions.json").write_text(
        json.dumps({"_reverse_engineered": True, "items": gaps},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (internal / "baseline_view.md").write_text(view, encoding="utf-8")

    print(f"archive ts: {archive / 'ts.json'}")
    print(f"rules: {len(ts['rules'])}, semantic_gaps: {len(gaps)}, "
          f"pending_load_mode: {sum(1 for g in gaps if g['code'] == 'load_mode_pending')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
