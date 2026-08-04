#!/usr/bin/env python3
"""
TS 制品组装器: rs_input.json + design_decisions.yaml -> ts.json + ts.md

designer agent 产出 design_decisions.yaml(纯设计判断),
本脚本负责把确定性字段(类型/来源/注释)从 rs_input.json 搬进来,
组装出结构 100% 正确的 ts.json, 并渲染 ts.md。

组装时内置校验:
  - 字段完整性: design_decisions 的 field_targets 并集 == rs_input 所有 target_column
  - 规则无冲突: 同一 target_column 不能出现在多个规则的 field_targets
  - 字段可查: field_targets 里的名字必须在 rs_input 里找得到

用法:
  python assemble_ts.py \
    --rs 10_project_deliver/{资产名}/ddlc_design_dev/_internal/rs_input.json \
    --decisions 10_project_deliver/{资产名}/ddlc_design_dev/_internal/design_decisions.yaml \
    --outdir 10_project_deliver/{资产名}/ddlc_design_dev

退出码: 0=成功, 1=校验失败(设计决策有问题), 2=文件/解析错误
"""

import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ============================================================
# 中文 transform_rule -> 英文 transform_type 映射
# ============================================================
TRANSFORM_MAP = {
    "直接复制": "direct",
    "数据加工": "aggregate",
    "赋值": "assign",
    "序列": "sequence",
}

# 标准审计字段模板（4个固定字段，用于补充缺失的审计字段）
STANDARD_AUDIT_TEMPLATE = {
    "del_flag":            {"type": "nvarchar(1)",                    "default": "'N'"},
    "crt_cycle_id":        {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "last_upd_cycle_id":   {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "dw_last_update_date": {"type": "timestamp(0) without time zone", "default": "CURRENT_TIMESTAMP"},
}
STANDARD_AUDIT_NAMES = set(STANDARD_AUDIT_TEMPLATE.keys())

# 标准参数（所有资产默认都有，脚本自动注入，designer 无需声明）
# 现仅批次号；如未来加标准参数，在此列表追加即可。
STANDARD_PARAMS = [
    {"name": "P_CYCLE_ID", "value_type": "string", "desc": "批次号"},
]


def build_exec_params(decisions):
    """组装 exec_params：标准参数自动注入 + 业务参数透传。

    返回 {param_name: {value_type, desc, standard}}。
    standard=true 表示脚本自动注入（所有资产都有）。
    """
    params = {}
    for sp in STANDARD_PARAMS:
        params[sp["name"]] = {
            "value_type": sp["value_type"],
            "desc": sp["desc"],
            "standard": True,
        }
    for p in decisions.get("params", []):
        params[p["name"]] = {
            "value_type": p.get("value_type", "string"),
            "desc": p.get("desc", ""),
            "standard": False,
        }
    return params


def is_audit_field(fm: dict) -> bool:
    """判断字段是否审计字段：备注优先（含'审计字段'），字段名兜底（匹配标准名）。"""
    remark = (fm.get("remark") or "").strip()
    if "审计字段" in remark:
        return True
    target = (fm.get("target_column") or "").strip().lower()
    return target in STANDARD_AUDIT_NAMES


# ============================================================
# 数据流图渲染（ts.md §5 用 mermaid 呈现）
# ============================================================

# 维度表 schema（OR 关系：表名含 dim 或 schema 在此集合里，即判为维表）
DIM_SCHEMAS = {"dim", "dwrdim", "dwrdim_dw1"}


def is_dim_table(schema: str, table: str) -> bool:
    """判断是否维表（任一命中即维表）：
    1. 表名包含 'dim'
    2. schema ∈ {dim, dwrdim, dwrdim_dw1}

    维表在数据流图里不画节点，降级为步骤节点的标注（避免源表过多拥挤）。
    """
    if "dim" in (table or "").lower():
        return True
    if (schema or "").lower() in DIM_SCHEMAS:
        return True
    return False


def _sanitize_node_id(text: str) -> str:
    """mermaid 节点 ID 只能字母/数字/下划线。把 . - 等替换成 _。"""
    return re.sub(r'[^A-Za-z0-9_]', '_', text or "")


def render_data_flow_mermaid(ts: dict) -> str:
    """从 ts.json 的 rules + data_flow 生成 mermaid flowchart TD 代码块。

    布局：上到下（TD），按 schedule_groups 分层。
    节点：表（源表/中间表/目标表/视图）+ 步骤（规则）混合。
    维表不画节点，降级为步骤标注。
    无规则时返回空串。
    """
    rules = ts.get("rules", {})
    if not rules:
        return ""

    df = ts.get("data_flow", {})
    schedule_groups = df.get("schedule_groups", [])
    # 没有 schedule_groups → 按 exec_sequence 兜底
    if not schedule_groups:
        schedule_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                           for code, r in rules.items()]

    lines = ['```mermaid']
    lines.append('flowchart TD')
    lines.append('')

    # 节点ID → className 的映射（末尾用 class 语句批量赋类，兼容 Typora）
    node_classes = {}  # {node_id: class_name}

    # --- 收集源表节点（全局去重，跨规则共享） ---
    declared_sources = {}  # source_table_key → {schema, table, node_id}
    declared_targets = set()  # 已声明的产出表 node_id
    edges = []  # [(from_id, to_id, dashed)]

    for code in list(rules.keys()):
        rule = rules[code]
        for st in rule.get("source_tables", []):
            sch = st.get("schema", "")
            tbl = st.get("table", "")
            if not tbl:
                continue
            key = f"{sch}.{tbl}"
            if key in declared_sources:
                continue
            declared_sources[key] = {
                "schema": sch,
                "table": tbl,
                "node_id": "src_" + _sanitize_node_id(tbl),
            }

    # --- 按 schedule_groups 分层画节点和边 ---
    for group in schedule_groups:
        for code in group.get("rules", []):
            rule = rules.get(code)
            if not rule:
                continue

            rule_name = rule.get("rule_name", "")
            target = rule.get("target_table", "")
            is_view = rule.get("is_view_step", False)
            step_id = "step_" + _sanitize_node_id(code)

            # 分类该规则的 source_tables
            dim_names = []      # 维表名（标注用）
            fact_sources = []   # 非维表（画节点）

            for st in rule.get("source_tables", []):
                sch = st.get("schema", "")
                tbl = st.get("table", "")
                if not tbl:
                    continue
                if is_dim_table(sch, tbl):
                    dim_names.append(tbl)
                else:
                    fact_sources.append((sch, tbl))

            # 步骤节点（含规则名 + 维表标注），不内联 :::，用 class 语句赋类
            step_label = f'{code}'
            if rule_name:
                step_label += f' / {rule_name}'
            if dim_names:
                dim_text = ", ".join(dim_names[:4])
                if len(dim_names) > 4:
                    dim_text += f" 等{len(dim_names)}张"
                step_label += f'<br/>关联维表: {dim_text}'
            lines.append(f'  {step_id}("{step_label}")')
            node_classes[step_id] = "step"

            # 画非维表源表节点 + 源表→步骤的边
            for sch, tbl in fact_sources:
                src_info = declared_sources.get(f"{sch}.{tbl}")
                if src_info:
                    src_id = src_info["node_id"]
                    if not src_info.get("_drawn"):
                        lines.append(f'  {src_id}["{tbl}<br/><small>{sch}</small>"]')
                        src_info["_drawn"] = True
                        node_classes[src_id] = "source"
                    edges.append((src_id, step_id, False))

            # 画产出表节点 + 步骤→产出表的边
            if target:
                tgt_id = "tbl_" + _sanitize_node_id(target)
                if tgt_id not in declared_targets:
                    if is_view:
                        cls = "view"
                    elif "tmp" in target.lower():
                        cls = "intermediate"
                    else:
                        cls = "target"
                    lines.append(f'  {tgt_id}["{target}"]')
                    declared_targets.add(tgt_id)
                    node_classes[tgt_id] = cls
                edges.append((step_id, tgt_id, is_view))

        lines.append('')

    # --- 画中间表→后续步骤的边 ---
    for dep in df.get("dependencies", []):
        inter_tbl = dep.get("intermediate_table", "")
        to_code = dep.get("to", "")
        if inter_tbl and to_code:
            inter_id = "tbl_" + _sanitize_node_id(inter_tbl)
            step_id = "step_" + _sanitize_node_id(to_code)
            edges.append((inter_id, step_id, False))

    # --- 输出所有边 ---
    for from_id, to_id, dashed in edges:
        arrow = "-.->" if dashed else "-->"
        lines.append(f'  {from_id} {arrow} {to_id}')

    # --- classDef 样式定义 ---
    lines.append('')
    lines.append('  classDef source fill:#dbeafe,stroke:#3b82f6,stroke-width:1.5px,color:#1e3a5f')
    lines.append('  classDef step fill:#ede9fe,stroke:#8b5cf6,stroke-width:1.5px,color:#4c1d95')
    lines.append('  classDef intermediate fill:#f1f5f9,stroke:#64748b,stroke-width:1.5px,color:#334155,stroke-dasharray:5 3')
    lines.append('  classDef target fill:#dcfce7,stroke:#22c55e,stroke-width:2.5px,color:#166534')
    lines.append('  classDef view fill:#e0e7ff,stroke:#6366f1,stroke-width:1.5px,color:#3730a3,stroke-dasharray:5 3')

    # --- class 语句批量赋类（兼容 Typora，不用 ::: 内联）---
    # 按 class_name 分组节点
    by_class = {}
    for nid, cls in node_classes.items():
        by_class.setdefault(cls, []).append(nid)
    for cls, nids in by_class.items():
        lines.append(f'  class {",".join(nids)} {cls}')

    lines.append('```')

    return "\n".join(lines)


# ============================================================
# 校验
# ============================================================
def validate_decisions(decisions, field_map):
    """校验 design_decisions 的字段分配是否和 rs_input 一致。

    field_map: { target_column: field_mapping_record }
    返回 errors 列表(空=通过)。
    """
    errors = []

    rules = decisions.get("rules", [])
    if not rules:
        errors.append("design_decisions 里没有定义任何规则(rules 为空)")
        return errors

    # 收集所有 field_targets, 检查重复和可查
    seen_fields = {}  # target_column -> rule_code
    rs_fields = set(field_map.keys())

    for rule in rules:
        code = rule.get("rule_code", "??")
        targets = rule.get("field_targets", [])
        if not targets:
            errors.append(f"规则 {code} 的 field_targets 为空")
            continue
        for t in targets:
            if t in seen_fields:
                errors.append(
                    f"字段 '{t}' 重复分配: 同时在 {seen_fields[t]} 和 {code} 里"
                )
            else:
                seen_fields[t] = code
            if t not in field_map:
                errors.append(
                    f"规则 {code} 的 field_targets 里 '{t}' 在 rs_input.json 里找不到"
                    f"(检查字段名拼写)"
                )

    # 检查覆盖完整性: rs_input 的所有字段都被分配了
    assigned = set(seen_fields.keys())
    missing = rs_fields - assigned
    if missing:
        errors.append(
            f"以下字段在 rs_input.json 里定义了, 但没有分配到任何规则: "
            f"{sorted(missing)}"
        )

    return errors


# ============================================================
# 组装 ts.json
# ============================================================
def build_field(field_rec, logic, rule_aliases):
    """从 rs_input 的 field_mapping 记录 + design_logic 组装 ts 的 field 对象。

    field_rec: rs_input.field_mappings 的一条记录
    logic: design_decisions 里该字段的 design_logic(可能为 None -> 用默认)
    rule_aliases: 该规则关联的源表别名集合(用于决定 source_fields)
    """
    transform_rule = field_rec.get("transform_rule", "直接复制")
    transform_type = TRANSFORM_MAP.get(transform_rule, "direct")

    alias = field_rec.get("source_alias", "")
    source_column = field_rec.get("source_column", "")
    source_table = field_rec.get("source_table", "")

    # design_logic: AI 写了就用 AI 的; 没写就根据 transform_type 生成默认
    if logic:
        design_logic = logic
    elif transform_type == "direct":
        design_logic = f"直取 {alias}.{source_column}" if alias else f"直取 {source_table}.{source_column}"
    elif transform_type == "assign":
        design_logic = "固定赋值"
    else:
        # 加工类字段没写 logic 是个问题, 但先给个占位, 校验层会警告
        design_logic = f"[需补充] 加工逻辑未写, transform_detail: {field_rec.get('transform_detail', '')}"

    return {
        "target_field": field_rec.get("target_column", ""),
        "field_type": field_rec.get("target_type", ""),
        "field_comment": field_rec.get("target_column_cn", ""),
        "transform_type": transform_type,
        "source_fields": [
            {
                "table": source_table,
                "field": source_column,
                "alias": alias,
            }
        ],
        "design_logic": design_logic,
    }


def build_rule(rule_dec, field_map, rs_source_tables):
    """组装一个规则对象。字段定义不在此产出（由 build_tables 按表汇总）。"""
    code = rule_dec.get("rule_code", "")
    targets = rule_dec.get("field_targets", [])
    logics = rule_dec.get("field_logics") or {}

    # 检查加工类字段是否写了 logic（字段定义已搬到 tables，这里只做口径完整性校验）
    missing_logic = []
    for t in targets:
        rec = field_map.get(t)
        if not rec:
            continue
        logic = logics.get(t)
        transform_rule = rec.get("transform_rule", "直接复制")
        transform_type = TRANSFORM_MAP.get(transform_rule, "direct")
        if transform_type != "direct" and not logic and not is_audit_field(rec):
            missing_logic.append(t)

    # source_tables: 从 rs_input 的 source_tables 按别名补全 schema/table
    rs_sources = {st.get("source_alias", ""): st for st in rs_source_tables}
    rule_sources = []
    aliases = rule_dec.get("source_aliases") or []
    if not aliases:
        aliases = list(rs_sources.keys())
    for sa in aliases:
        rs_st = rs_sources.get(sa, {})
        rule_sources.append({
            "schema": rs_st.get("source_schema", ""),
            "table": rs_st.get("source_table", ""),
            "alias": sa,
        })

    return {
        "rule_name": rule_dec.get("rule_name", ""),
        "scenario": rule_dec.get("scenario", ""),
        "exec_sequence": rule_dec.get("exec_sequence", 1),
        "target_table": rule_dec.get("target_table", ""),
        "is_view_step": rule_dec.get("is_view_step", False),
        "design_intent": rule_dec.get("design_intent", ""),
        "load_mode": rule_dec.get("load_mode", "truncate_table"),
        "source_tables": rule_sources,
        "ctes": rule_dec.get("ctes", []),
        "grain": rule_dec.get("grain", {}),
        "joins": rule_dec.get("joins", []),
        "join_safety": rule_dec.get("join_safety", []),
        "field_targets": targets,
        "field_logics": logics,
    }, missing_logic


def infer_logical_group(schema: str) -> str:
    """按 schema 推断逻辑集群（TO GROUP）。"""
    if not schema:
        return "LC_DW1"
    s = schema.lower()
    if "drt" in s:
        return "gtoup_version1"
    return "LC_DW1"


def build_tables(rules: dict, decisions: dict, field_map: dict, rs_input: dict, target_f_table: str) -> dict:
    """组装 tables 段（表实体，含字段定义 + 物理属性）。

    - 字段定义从 rs_input.field_mappings 按 rule→target_table→field_targets 分组搬入
    - 物理属性从 decisions.tables 取，缺失用默认
    - 审计字段补充到最终目标表的 fields
    - I 视图不放 tables（无物理属性，字段=F表镜像）
    """
    dec_tables = decisions.get("tables", {})
    supplemented = []  # 审计字段补充（由 build_design 算出，这里通过参数传入更解耦，但简化处理从 design 读不到）
    # 审计字段：从 rs_input 识别来源提供的 + 标准模板
    all_fm = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fm if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}
    supplemented_names = STANDARD_AUDIT_NAMES - source_audit_names

    # 最终目标表名（短名，不含 schema）
    final_table_short = target_f_table.rsplit(".", 1)[-1] if "." in target_f_table else target_f_table

    tables = {}
    for code, rule in rules.items():
        tbl = rule.get("target_table", "")
        if not tbl or rule.get("is_view_step"):
            continue
        tbl_short = tbl.rsplit(".", 1)[-1] if "." in tbl else tbl

        # 跳过已处理的表（多 rule 写同表，只建一次字段集）
        if tbl_short in tables:
            continue

        # 判断表类型
        is_final = (tbl_short == final_table_short)
        tbl_type = "target" if is_final else "intermediate"

        # 字段定义：从 field_map 按 field_targets 组装
        fields = []
        for tname in rule.get("field_targets", []):
            rec = field_map.get(tname)
            if not rec:
                continue
            f = build_field(rec, None, rule.get("source_aliases"))
            fields.append(f)

        # 目标表补充审计字段
        if is_final:
            for aname in supplemented_names:
                spec = STANDARD_AUDIT_TEMPLATE.get(aname, {})
                # 检查是否已在 fields 里（防重复）
                existing_names = {f["target_field"].lower() for f in fields}
                if aname.lower() not in existing_names:
                    fields.append({
                        "target_field": aname,
                        "field_type": spec.get("type", ""),
                        "field_comment": "审计字段（自动补充）",
                        "transform_type": "assign",
                        "source_fields": [],
                        "design_logic": f"固定赋值 {spec.get('default', '')}",
                    })

        # 物理属性
        dec_tbl = dec_tables.get(tbl_short, {})
        # schema 用于推断逻辑集群
        tbl_schema = ""
        for fm in all_fm:
            pass  # schema 从 target_table 或 meta 取更准
        # 从 target_table 拆 schema
        if "." in tbl:
            tbl_schema = tbl.split(".")[0]

        # 分布键：per-table 声明优先；没填则用旧版全局 distribution_key 兜底
        dec_dist = dec_tbl.get("distribution_key", [])
        if not dec_dist:
            dec_dist = decisions.get("distribution_key", [])

        # 分布方式：HASH（默认）/ ROUNDROBIN / REPLICATION
        # 有分布键 → HASH；无分布键 → ROUNDROBIN；designer 可显式指定
        distribute_type = dec_tbl.get("distribute_type", "")
        if not distribute_type:
            distribute_type = "HASH" if dec_dist else "ROUNDROBIN"

        tables[tbl_short] = {
            "type": tbl_type,
            "distribution_key": dec_dist,
            "distribute_type": distribute_type,
            "partition": dec_tbl.get("partition", ""),
            "storage": dec_tbl.get("storage", "column"),
            "logical_group": dec_tbl.get("logical_group", "") or infer_logical_group(tbl_schema),
            "fields": fields,
        }

    return tables


def build_meta(rs_input, decisions):
    """组装 meta(从 rs_input 搬确定性数据)。"""
    rs_meta = rs_input.get("meta", {})
    target = rs_meta.get("target", {})

    # rs_input 的 target 已有 f_table 和 i_view（preprocess 从 _i 推导）
    f_table = target.get("f_table", {})
    i_view = target.get("i_view", {})

    # 兜底：如果 rs_input 还是旧格式（只有 schema/table/cn），推导一下
    if not f_table and target.get("table"):
        table_name = target["table"]
        if table_name.endswith("_i"):
            f_table = {"schema": target.get("schema", ""), "table": table_name[:-2] + "_f", "cn": target.get("cn", "")}
            i_view = {"schema": target.get("schema", ""), "table": table_name, "cn": target.get("cn", "")}
        else:
            f_table = {"schema": target.get("schema", ""), "table": table_name, "cn": target.get("cn", "")}
            i_view = {"schema": target.get("schema", ""), "table": table_name[:-2] + "_i" if table_name.endswith("_f") else table_name + "_i", "cn": target.get("cn", "")}

    # source_tables(从 rs_input 搬, 按表去重——同一张表多次关联只列一次)
    seen_tables = {}  # table -> {schema, table, table_cn, aliases}
    for st in rs_input.get("source_tables", []):
        t = st.get("source_table", "")
        a = st.get("source_alias", "")
        if not t:
            continue
        if t not in seen_tables:
            seen_tables[t] = {
                "schema": st.get("source_schema", ""),
                "table": t,
                "table_cn": st.get("source_table_cn", ""),
                "aliases": [],
            }
        if a and a not in seen_tables[t]["aliases"]:
            seen_tables[t]["aliases"].append(a)
    # 转成列表，别名合并成逗号分隔
    source_tables = []
    for st_info in seen_tables.values():
        st_info["alias"] = ", ".join(st_info.pop("aliases"))
        source_tables.append(st_info)

    # 调度: rs_input 给大框架 + designer 细化
    rs_sched = rs_input.get("schedule", {})
    dec_sched = decisions.get("schedule", {})

    # LTS 调度参数（designer 声明，默认含 V_CYCLE_ID→P_CYCLE_ID + V_GROUP_CODE）
    default_lts_params = [
        {"lts_var": "V_CYCLE_ID", "etl_param": "P_CYCLE_ID", "desc": "批次号"},
        {"lts_var": "V_GROUP_CODE", "etl_param": "", "desc": "规则组编码"},
    ]
    lts_params = dec_sched.get("lts_params", default_lts_params)

    # upstream: rs_input 已有的 + designer 新增的
    upstream = list(rs_sched.get("upstream", []))
    for u in dec_sched.get("upstream_added", []):
        upstream.append({"table": u.get("table", ""), "task": u.get("task", ""), "source": "designer"})

    # I 视图调度（如有直封视图）
    view_sched = {}
    i_view = target.get("i_view", {})
    if i_view and i_view.get("table"):
        dec_view = dec_sched.get("view", {})
        view_task = dec_view.get("task_name", "")
        view_cron = dec_view.get("cron", "")
        # 视图上游自动补：依赖 F 表任务
        f_task = dec_sched.get("task_name", "")
        f_table_short = target.get("f_table", {}).get("table", "")
        view_upstream = [{"table": f_table_short, "task": f_task}] if f_task else []
        view_sched = {
            "task_name": view_task,
            "cron": view_cron,
            "upstream": view_upstream,
        }

    schedule = {
        "task_name": dec_sched.get("task_name", ""),
        "cron": dec_sched.get("cron", ""),
        "owner": rs_meta.get("owner", {}).get("person", ""),
        "exec_params": build_exec_params(decisions),
        "lts_params": lts_params,
        "upstream": upstream,
        "view": view_sched,
    }

    # 字段统计：识别审计字段（来源提供的），其余为业务字段
    all_fields = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fields if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}
    # 来源没提供的审计字段，需要补充
    supplemented = STANDARD_AUDIT_NAMES - source_audit_names
    business_count = len(all_fields) - len(source_audit)
    audit_count = len(source_audit) + len(supplemented)  # 来源的 + 补充的 = 总审计数

    load_strat = rs_meta.get("load_strategy", {})
    strategy = load_strat.get("strategy", "")
    return {
        "target": {
            "f_table": f_table,
            "i_view": i_view,
        },
        "grain": rs_meta.get("grain", ""),
        "load_strategy": {
            "strategy": strategy,
            "label": "",
            "delete_mode": "",
        },
        "field_count": {
            "business": business_count,
            "audit": audit_count,
            "total": business_count + audit_count,
        },
        "source_tables": source_tables,
        "schedule": schedule,
    }


def build_design(decisions, rs_input):
    """组装 design。audit_fields 智能处理：来源有用来源的，来源没的用标准模板补充。"""
    comp = decisions.get("complexity_analysis", {})

    # 审计字段智能处理
    all_fields = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fields if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}

    audit_fields = {}
    # 来源提供的审计字段：用来源的类型和默认值
    for fm in source_audit:
        name = (fm.get("target_column") or "").lower()
        audit_fields[name] = {
            "type": fm.get("target_type", ""),
            "default": (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip(),
            "source": "mapping",  # 标记来自 mapping
        }
    # 来源没提供的审计字段：用标准模板补充
    for name, spec in STANDARD_AUDIT_TEMPLATE.items():
        if name not in source_audit_names:
            audit_fields[name] = {**spec, "source": "supplemented"}  # 标记自动补充

    supplemented = STANDARD_AUDIT_NAMES - source_audit_names

    return {
        "complexity_analysis": {
            "join_count": comp.get("join_count", 0),
            "has_grain_change": comp.get("has_grain_change", False),
            "grain_change_detail": comp.get("grain_change_detail", ""),
            "multi_step_fields": comp.get("multi_step_fields", 0),
            "aggregation_after_join": comp.get("aggregation_after_join", False),
            "segmentation_decision": comp.get("segmentation_decision", ""),
            "segmentation_reason": comp.get("segmentation_reason", ""),
        },
        "audit_fields": audit_fields,
        "audit_supplemented": sorted(supplemented),
        "business_key": decisions.get("business_key", []),
        "business_key_design": decisions.get("business_key_design", {}),
    }


def assemble_ts(rs_input, decisions):
    """组装完整 ts.json dict。"""
    # 建 field_map: target_column -> field_mapping 记录
    field_map = {}
    for fm in rs_input.get("field_mappings", []):
        tc = fm.get("target_column", "")
        if tc:
            field_map[tc] = fm

    meta = build_meta(rs_input, decisions)
    design = build_design(decisions, rs_input)

    rules = {}
    all_missing_logic = []
    for rule_dec in decisions.get("rules", []):
        code = rule_dec.get("rule_code", "")
        rule_obj, missing_logic = build_rule(rule_dec, field_map, rs_input.get("source_tables", []))
        rules[code] = rule_obj
        if missing_logic:
            all_missing_logic.append((code, missing_logic))

    # 组装 tables 段（表实体：字段定义 + 物理属性）
    f_table_full = meta.get("target", {}).get("f_table", {}).get("table", "")
    tables = build_tables(rules, decisions, field_map, rs_input, f_table_full)

    ts = {
        "version": "1.0.0",
        "spec_type": "ts",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "assemble_ts.py",
        "meta": meta,
        "design": design,
        "tables": tables,
        "rules": rules,
        "data_flow": decisions.get("data_flow", {}),
        "dq_rules": decisions.get("dq_rules", []),
    }
    return ts, all_missing_logic, field_map


# ============================================================
# 渲染 ts.md(从 ts.json 投影, 7章)
# ============================================================
def render_md(ts):
    """从 ts.json 渲染 ts.md(人读投影)。"""
    meta = ts["meta"]
    target = meta["target"]
    rules = ts["rules"]
    design = ts["design"]
    tables = ts.get("tables", {})

    lines = []
    lines.append(f"# ETL 技术规格(TS)")
    lines.append("")
    lines.append(f"> 目标表: `{target['f_table']['schema']}.{target['f_table']['table']}`"
                 f"({target['f_table']['cn']}) - 生成 {ts['generated_at']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §1 概述
    lines.append("## 1. 概述")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| **F 表** | `{target['f_table']['schema']}.{target['f_table']['table']}`（{target['f_table']['cn']}） |")
    i_view = target.get("i_view", {})
    if i_view and i_view.get("table"):
        lines.append(f"| **I 视图** | `{i_view.get('schema', '')}.{i_view.get('table', '')}`（F表镜像，对外查询） |")
    # 业务主键（替代原"目标粒度"——主键即粒度定义）
    bk = design.get("business_key", [])
    lines.append(f"| **业务主键** | {', '.join(bk) if bk else '-'} |")
    # 写入策略：全量可重刷 / 增量（详见规则详情）
    all_truncate = all(r.get("load_mode") == "truncate_table" for r in rules.values())
    load_label = "全量（可随时重刷）" if all_truncate else "增量（详见规则详情）"
    lines.append(f"| **写入策略** | {load_label} |")
    fc = meta["field_count"]
    lines.append(f"| **字段统计** | {fc['total']} |")
    # 规则数（含直封视图提示）
    has_view = any(r.get("is_view_step") for r in rules.values())
    rule_label = f"{len(rules)}"
    if has_view:
        rule_label += "（含直封视图）"
    lines.append(f"| **规则数** | {rule_label} |")
    lines.append("")
    lines.append("**来源表**:")
    lines.append("")
    lines.append("| # | 表名 | 中文名 | 别名 |")
    lines.append("|---|------|--------|------|")
    for i, st in enumerate(meta["source_tables"], 1):
        lines.append(f"| {i} | {st['schema']}.{st['table']} | {st['table_cn']} | {st['alias']} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §2 表模型设计（统一表格，目标表优先）
    lines.append("## 2. 表模型设计")
    lines.append("")
    f_table_short = target["f_table"]["table"]
    i_view_short = target["i_view"].get("table", "")

    def _short_desc(text: str, limit: int = 30) -> str:
        """截短说明：取第一个逗号/句号前的内容，或限制长度。"""
        if not text:
            return ""
        for sep in ["，", "。", ",", "."]:
            if sep in text:
                text = text.split(sep)[0]
                break
        return text[:limit] + "…" if len(text) > limit else text

    def _dist_label(t):
        """分布类型+分布键合并显示，如 HASH(product_id) / ROUNDROBIN / REPLICATION"""
        dtype = t.get("distribute_type", "HASH")
        dkeys = t.get("distribution_key", [])
        if dtype == "HASH" and dkeys:
            return f"HASH({', '.join(dkeys)})"
        elif dtype == "REPLICATION":
            return "REPLICATION"
        else:
            return dtype or "—"

    # 排序：目标F表 → 中间表 → 视图
    lines.append("| 表名 | 类型 | 分布 | 分区 | 字段数 | 说明 |")
    lines.append("|------|------|------|------|--------|------|")
    # 目标 F 表
    if f_table_short in tables:
        t = tables[f_table_short]
        part = t.get("partition") or "—"
        fcount = len(t.get("fields", []))
        lines.append(f"| `{f_table_short}` | 目标F表 | {_dist_label(t)} | {part} | {fcount} | {target['f_table'].get('cn', '')} |")
    # 中间表
    for tname, t in tables.items():
        if t.get("type") == "intermediate":
            part = t.get("partition") or "—"
            fcount = len(t.get("fields", []))
            # 找对应规则的 design_intent，截短成简述
            intent = ""
            for r in rules.values():
                rt = r.get("target_table", "")
                if rt.rsplit(".", 1)[-1] == tname or rt == tname:
                    intent = _short_desc(r.get("design_intent", ""))
                    break
            lines.append(f"| `{tname}` | 中间表 | {_dist_label(t)} | {part} | {fcount} | {intent} |")
    # 视图（无物理属性）
    if i_view_short:
        f_fields = len(tables.get(f_table_short, {}).get("fields", []))
        lines.append(f"| `{i_view_short}` | 直封视图 | — | — | 同F表 | F表镜像，对外查询 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §3 复杂度分析
    lines.append("## 3. 复杂度分析与分段决策")
    lines.append("")
    comp = design["complexity_analysis"]
    lines.append("| 因素 | 值 | 阈值 |")
    lines.append("|------|-----|------|")
    lines.append(f"| JOIN 表数量 | {comp['join_count']} | >12 触发分段 |")
    grain_label = "有" if comp['has_grain_change'] else "无"
    lines.append(f"| 粒度变化 | {grain_label} | 有即评估分段 |")
    lines.append(f"| 多步骤加工字段 | {comp['multi_step_fields']} | ≥5 触发分段 |")
    lines.append(f"| 聚合后关联 | {'是' if comp['aggregation_after_join'] else '否'} | 是即评估分段 |")
    lines.append("")
    if comp.get("grain_change_detail"):
        lines.append(f"> 粒度变化说明: {comp['grain_change_detail']}")
        lines.append("")
    seg = comp.get("segmentation_decision", "")
    lines.append(f"**分段结论**: **{seg}**")
    lines.append("")
    if comp.get("segmentation_reason"):
        lines.append(f"> {comp['segmentation_reason']}")
        lines.append("")
    lines.append("---")
    lines.append("")

    # §4 规则详情
    lines.append("## 4. 规则详情")
    lines.append("")
    for code, r in rules.items():
        lines.append(f"### {code} - {r['rule_name']}")
        lines.append("")
        lines.append("| 项目 | 内容 |")
        lines.append("|------|------|")
        # 场景：默认(default)不展示，非默认才显示
        scenario = r.get("scenario", "")
        if scenario and scenario != "default":
            lines.append(f"| 场景 | {scenario} |")
        lines.append(f"| 执行序 | {r['exec_sequence']} |")
        lines.append(f"| 产出表 | `{r['target_table']}` |")
        lines.append(f"| 写入方式 | {r.get('load_mode', '-')} |")
        if r.get("design_intent"):
            lines.append(f"| 设计意图 | {r['design_intent']} |")
        lines.append(f"| 字段数 | {len(r.get('field_targets', []))} |")
        lines.append("")

        # 关联安全：只有有风险的（join_key_unique=false）才展示
        risky_joins = [js for js in r.get("join_safety", []) if not js.get("join_key_unique")]
        if risky_joins:
            lines.append("**关联风险**:")
            lines.append("")
            for js in risky_joins:
                tbl = js.get("table", "")
                strategy = js.get("strategy", "")
                lines.append(f"- `{tbl}`: {strategy}")
            lines.append("")

        # 重要字段逻辑：只写有口径的、非审计字段
        logics = r.get("field_logics", {})
        if logics:
            lines.append("**字段逻辑**:")
            lines.append("")
            for name, logic in logics.items():
                lines.append(f"- `{name}`: {logic}")
            lines.append("")
        lines.append("---")
        lines.append("")

    # §5 数据流向（只留数据流图，血缘/执行顺序已被图覆盖）
    lines.append("## 5. 数据流向")
    lines.append("")
    mermaid_graph = render_data_flow_mermaid(ts)
    if mermaid_graph:
        lines.append(mermaid_graph)
        lines.append("")
    lines.append("---")
    lines.append("")

    # §6 调度配置
    lines.append("## 6. 调度配置")
    lines.append("")
    sched = meta.get("schedule", {})

    # F 表调度
    lines.append("### F 表调度")
    lines.append("")
    lines.append("| 配置项 | 值 |")
    lines.append("|--------|-----|")
    lines.append(f"| 调度任务 | {sched.get('task_name') or '-'} |")
    lines.append(f"| 调度周期 | {sched.get('cron') or '-'} |")
    lines.append("")

    # LTS 参数
    lts_params = sched.get("lts_params", [])
    if lts_params:
        lines.append("**LTS 参数**:")
        lines.append("")
        lines.append("| LTS 变量 | 赋值给 ETL 参数 | 说明 |")
        lines.append("|----------|----------------|------|")
        for p in lts_params:
            etl = p.get("etl_param", "") or "—"
            lines.append(f"| {p.get('lts_var', '')} | {etl} | {p.get('desc', '')} |")
        lines.append("")

    # 上游依赖
    upstream = sched.get("upstream", [])
    if upstream:
        lines.append("**上游依赖**:")
        lines.append("")
        lines.append("| 源表 | 调度任务 |")
        lines.append("|------|---------|")
        for u in upstream:
            lines.append(f"| {u.get('table', '')} | {u.get('task', '') or '-'} |")
        lines.append("")

    # I 视图调度
    view_sched = sched.get("view", {})
    if view_sched and view_sched.get("task_name"):
        lines.append("### I 视图调度")
        lines.append("")
        lines.append("| 配置项 | 值 |")
        lines.append("|--------|-----|")
        lines.append(f"| 调度任务 | {view_sched.get('task_name', '-')} |")
        lines.append(f"| 调度周期 | {view_sched.get('cron', '-') or '-'} |")
        lines.append("")
        v_upstream = view_sched.get("upstream", [])
        if v_upstream:
            lines.append("**上游依赖**:")
            lines.append("")
            lines.append("| 源表 | 调度任务 |")
            lines.append("|------|---------|")
            for u in v_upstream:
                lines.append(f"| {u.get('table', '')} | {u.get('task', '') or '-'} |")
            lines.append("")

    lines.append("---")
    lines.append("")

    # §7 DQ（从 RS L06 搬入，类型跟 RS 保持一致）
    lines.append("## 7. 数据质量检查(DQ)")
    lines.append("")
    dq = ts.get("dq_rules", [])
    if dq:
        lines.append("| 检查范围 | 检查类型 | 规则名称 | 规则描述 |")
        lines.append("|----------|----------|----------|----------|")
        for d in dq:
            lines.append(f"| {d.get('scope', '')} | {d.get('check_type', '')} | {d.get('rule_name', '')} | {d.get('rule_desc', '')} |")
    else:
        lines.append("*(本表无 DQ 要求)*")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="TS 制品组装器: rs_input.json + design_decisions.yaml -> ts.json + ts.md"
    )
    parser.add_argument("--rs", required=True, help="rs_input.json 路径")
    parser.add_argument("--decisions", required=True, help="design_decisions.yaml 路径")
    parser.add_argument("--outdir", required=True, help="输出目录(ts.json + ts.md 写到这里)")
    args = parser.parse_args()

    # 1. 读 rs_input.json
    rs_path = Path(args.rs)
    if not rs_path.exists():
        print(f"错误: rs_input.json 不存在: {rs_path}", file=sys.stderr)
        sys.exit(2)
    try:
        rs_input = json.loads(rs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误: rs_input.json 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 2. 读 design_decisions.yaml
    dec_path = Path(args.decisions)
    if not dec_path.exists():
        print(f"错误: design_decisions.yaml 不存在: {dec_path}", file=sys.stderr)
        sys.exit(2)
    try:
        decisions = yaml.safe_load(dec_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"错误: design_decisions.yaml 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(decisions, dict):
        print("错误: design_decisions.yaml 顶层应为字典(mapping)", file=sys.stderr)
        sys.exit(2)

    # 3. 建 field_map 并校验
    field_map = {}
    for fm in rs_input.get("field_mappings", []):
        tc = fm.get("target_column", "")
        if tc:
            field_map[tc] = fm

    print(f"rs_input: {len(field_map)} 个目标字段, {len(rs_input.get('source_tables', []))} 个源表")
    print(f"design_decisions: {len(decisions.get('rules', []))} 个规则")

    errors = validate_decisions(decisions, field_map)
    if errors:
        print("\n[校验失败] design_decisions 有以下问题:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\n请修正 design_decisions.yaml 后重跑。", file=sys.stderr)
        sys.exit(1)

    # 4. 组装 ts.json
    ts, missing_logic, _ = assemble_ts(rs_input, decisions)

    # 加工字段缺 logic 的警告(不阻断, 但提醒)
    if missing_logic:
        print("\n[警告] 以下加工字段未写 design_logic(已填占位, 请补):", file=sys.stderr)
        for code, fields in missing_logic:
            print(f"  {code}: {fields}", file=sys.stderr)

    # 5. 写出
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 从 ts.json 取资产名（f_table 表名）用于 md 文件命名
    asset_name = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("table", "ts")
    ts_json_path = outdir / "ts.json"
    ts_json_path.write_text(json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产出 ts.json: {ts_json_path}")

    ts_md_path = outdir / f"{asset_name}_ts.md"
    ts_md_path.write_text(render_md(ts), encoding="utf-8")
    print(f"产出 {asset_name}_ts.md: {ts_md_path}")

    # 6. 摘要
    rules = ts["rules"]
    scenarios = set(r["scenario"] for r in rules.values() if r["scenario"])
    print(f"\n[完成] {len(rules)} 个规则, {len(scenarios)} 个场景, "
          f"{ts['meta']['field_count']['total']} 个字段(含审计)")


if __name__ == "__main__":
    main()
