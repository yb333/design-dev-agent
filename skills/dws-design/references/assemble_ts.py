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


def is_audit_field(fm: dict) -> bool:
    """判断字段是否审计字段：备注优先（含'审计字段'），字段名兜底（匹配标准名）。"""
    remark = (fm.get("remark") or "").strip()
    if "审计字段" in remark:
        return True
    target = (fm.get("target_column") or "").strip().lower()
    return target in STANDARD_AUDIT_NAMES


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
    """组装一个规则对象。"""
    code = rule_dec.get("rule_code", "")
    targets = rule_dec.get("field_targets", [])
    logics = rule_dec.get("field_logics") or {}

    fields = []
    missing_logic = []
    for t in targets:
        rec = field_map.get(t)
        if not rec:
            continue  # validate 阶段已报错
        logic = logics.get(t)
        f = build_field(rec, logic, rule_dec.get("source_aliases"))
        # 加工/赋值/序列类字段没写 logic -> 记录警告
        # 排除审计字段（赋值类审计字段的逻辑已从 mapping 的 transform_detail 搬入）
        if f["transform_type"] != "direct" and not logic and not is_audit_field(rec):
            missing_logic.append(t)
        fields.append(f)

    # source_tables: 从 rs_input 的 source_tables 按别名补全 schema/table
    rs_sources = {st.get("source_alias", ""): st for st in rs_source_tables}
    rule_sources = []
    for sa in (rule_dec.get("source_aliases") or []):
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
        "source_tables": rule_sources,
        "ctes": rule_dec.get("ctes", []),
        "grain": rule_dec.get("grain", {}),
        "joins": rule_dec.get("joins", []),
        "join_safety": rule_dec.get("join_safety", []),
        "fields": fields,
        "field_count": len(fields),
    }, missing_logic


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

    # source_tables(从 rs_input 搬, 去重)
    seen = set()
    source_tables = []
    for st in rs_input.get("source_tables", []):
        t = st.get("source_table", "")
        a = st.get("source_alias", "")
        key = (t, a)
        if key in seen:
            continue
        seen.add(key)
        source_tables.append({
            "schema": st.get("source_schema", ""),
            "table": t,
            "table_cn": st.get("source_table_cn", ""),
            "alias": a,
        })

    # 调度: rs_input 给大框架 + designer 细化
    rs_sched = rs_input.get("schedule", {})
    dec_sched = decisions.get("schedule", {})
    schedule = {
        "task_name": dec_sched.get("task_name", ""),
        "cron": dec_sched.get("cron", ""),
        "task_group": dec_sched.get("task_group", ""),
        "project": dec_sched.get("project", ""),
        "owner": rs_meta.get("owner", {}).get("person", ""),
        "exec_params": {},
        "upstream": rs_sched.get("upstream", []),
        "execution_platform": {},
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
        "audit_supplemented": sorted(supplemented),  # 记录哪些是补充的（ts.md 标注用）
        "distribution_key": decisions.get("distribution_key", []),
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

    # 补充审计字段：来源没提供的，加到最终规则（产出目标F表的最后规则）的 fields 里
    supplemented = design.get("audit_supplemented", [])
    if supplemented and rules:
        # 找最终规则：exec_sequence 最大的规则
        final_code = max(rules.keys(), key=lambda c: rules[c].get("exec_sequence", 0))
        for name in supplemented:
            spec = STANDARD_AUDIT_TEMPLATE.get(name, {})
            rules[final_code]["fields"].append({
                "target_field": name,
                "field_type": spec.get("type", ""),
                "field_comment": "审计字段（自动补充）",
                "transform_type": "assign",
                "source_fields": [],
                "design_logic": f"固定赋值 {spec.get('default', '')}",
            })
            rules[final_code]["field_count"] += 1

    ts = {
        "version": "1.0.0",
        "spec_type": "ts",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "assemble_ts.py",
        "meta": meta,
        "design": design,
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
    lines.append(f"| **F 表** | `{target['f_table']['schema']}.{target['f_table']['table']}`({target['f_table']['cn']}) |")
    lines.append(f"| **I 视图** | `{target['i_view']['schema']}.{target['i_view']['table']}`(F表镜像) |")
    lines.append(f"| **目标粒度** | {meta['grain']} |")
    lines.append(f"| **写入策略** | {meta['load_strategy']['strategy']} |")
    lines.append(f"| **分布键** | {', '.join(design['distribution_key']) or '-'} |")
    fc = meta["field_count"]
    lines.append(f"| **字段统计** | 业务 {fc['business']} + 审计 {fc['audit']} = 总计 {fc['total']} |")
    # 标注补充的审计字段
    supplemented = design.get("audit_supplemented", [])
    if supplemented:
        lines.append(f"| **审计字段来源** | RS/mapping 未提供 {len(supplemented)} 个审计字段（{'、'.join(supplemented)}），已自动补充 |")
    else:
        lines.append(f"| **审计字段来源** | 全部来自 RS/mapping |")
    lines.append(f"| **规则数** | {len(rules)} |")
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

    # §2 表模型设计
    lines.append("## 2. 表模型设计")
    lines.append("")
    lines.append(f"- **F表**: `{target['f_table']['table']}`(存数据)")
    lines.append(f"- **I视图**: `{target['i_view']['table']}`(F表镜像, 对外查询)")
    lines.append(f"- **分布键**: {', '.join(design['distribution_key']) or '待定'}")
    lines.append("")
    # 中间表(非目标表的规则产出)
    mid_rules = [c for c, r in rules.items() if r["target_table"] and r["target_table"] != target["f_table"]["table"]]
    if mid_rules:
        lines.append("**中间表**:")
        lines.append("")
        lines.append("| 规则 | 表名 | 粒度 | 用途 |")
        lines.append("|------|------|------|------|")
        for c in mid_rules:
            r = rules[c]
            lines.append(f"| {c} | {r['target_table']} | {r['grain'].get('output', '-')} | {r['design_intent']} |")
        lines.append("")
    lines.append("---")
    lines.append("")

    # §3 复杂度分析
    lines.append("## 3. 复杂度分析与分段决策")
    lines.append("")
    comp = design["complexity_analysis"]
    lines.append("| 因素 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| JOIN 表数量 | {comp['join_count']} |")
    lines.append(f"| 粒度变化 | {'有' if comp['has_grain_change'] else '无'} ({comp['grain_change_detail']}) |")
    lines.append(f"| 多步骤加工字段 | {comp['multi_step_fields']} |")
    lines.append(f"| 聚合后关联 | {'是' if comp['aggregation_after_join'] else '否'} |")
    lines.append("")
    lines.append(f"**分段结论**: {comp['segmentation_decision']}")
    lines.append(f"**理由**: {comp['segmentation_reason']}")
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
        lines.append(f"| 场景 | {r['scenario'] or '-'} |")
        lines.append(f"| 执行序 | {r['exec_sequence']} |")
        lines.append(f"| 产出表 | `{r['target_table']}` |")
        lines.append(f"| 设计意图 | {r['design_intent']} |")
        lines.append(f"| 字段数 | {r['field_count']} |")
        lines.append("")
        # 关联策略
        if r.get("joins"):
            lines.append("**关联策略**:")
            lines.append("")
            lines.append("| 别名 | JOIN | 条件 |")
            lines.append("|------|------|------|")
            for j in r["joins"]:
                lines.append(f"| {j.get('alias', '')} | {j.get('type', '')} | {j.get('condition', '')} |")
            lines.append("")
        # 关联安全
        if r.get("join_safety"):
            lines.append("**关联安全**:")
            lines.append("")
            lines.append("| 表 | JOIN键唯一 | 对齐策略 |")
            lines.append("|------|-----------|----------|")
            for js in r["join_safety"]:
                lines.append(f"| {js.get('table', '')} | {'是' if js.get('join_key_unique') else '否'} | {js.get('strategy', '')} |")
            lines.append("")
        # 字段概要(只统计+抽样, 不全列)
        from collections import Counter
        type_counts = Counter(f["transform_type"] for f in r["fields"])
        lines.append("**字段概要**:")
        lines.append("")
        lines.append("| 转换类型 | 数量 |")
        lines.append("|----------|------|")
        for tt, cnt in type_counts.most_common():
            lines.append(f"| {tt} | {cnt} |")
        lines.append(f"| assign(审计) | {len(design['audit_fields'])} |")
        lines.append("")
        # 加工字段抽样(design_logic)
        logic_fields = [f for f in r["fields"] if f["transform_type"] != "direct"]
        if logic_fields:
            lines.append("**加工字段抽样**(完整字段见 ts.json):")
            lines.append("")
            for f in logic_fields[:5]:
                lines.append(f"- `{f['target_field']}`: {f['design_logic']}")
            if len(logic_fields) > 5:
                lines.append(f"- ...(共 {len(logic_fields)} 个加工字段)")
            lines.append("")
        lines.append("---")
        lines.append("")

    # §5 数据流向
    lines.append("## 5. 数据流向")
    lines.append("")
    df = ts.get("data_flow", {})
    deps = df.get("dependencies", [])
    if deps:
        lines.append("**血缘关系**:")
        lines.append("")
        lines.append("| from | to | 中间表 |")
        lines.append("|------|-----|--------|")
        for d in deps:
            lines.append(f"| {d.get('from', '')} | {d.get('to', '')} | {d.get('intermediate_table', '-')} |")
        lines.append("")
    groups = df.get("schedule_groups", [])
    if groups:
        lines.append("**执行顺序**:")
        lines.append("")
        lines.append("| 顺序 | 规则 |")
        lines.append("|------|------|")
        for g in groups:
            lines.append(f"| {g.get('sequence', '')} | {', '.join(g.get('rules', []))} |")
        lines.append("")
    lines.append("---")
    lines.append("")

    # §6 调度
    lines.append("## 6. 调度配置")
    lines.append("")
    sched = meta["schedule"]
    lines.append("| 配置项 | 值 |")
    lines.append("|--------|-----|")
    lines.append(f"| 调度任务 | {sched['task_name'] or '-'} |")
    lines.append(f"| 调度周期 | {sched['cron'] or '-'} |")
    lines.append(f"| 任务组 | {sched['task_group'] or '-'} |")
    if sched.get("upstream"):
        lines.append("")
        lines.append("**上游依赖**:")
        for u in sched["upstream"]:
            lines.append(f"- {u.get('table', '')} <- {u.get('task', '')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §7 DQ
    lines.append("## 7. 数据质量检查(DQ)")
    lines.append("")
    dq = ts.get("dq_rules", [])
    if dq:
        lines.append("| 规则ID | 名称 | 类型 | 对象 |")
        lines.append("|--------|------|------|------|")
        for d in dq:
            lines.append(f"| {d.get('rule_id', '')} | {d.get('rule_name', '')} | {d.get('check_type', '')} | {d.get('target', '')} |")
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

    ts_json_path = outdir / "ts.json"
    ts_json_path.write_text(json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产出 ts.json: {ts_json_path}")

    ts_md_path = outdir / "ts.md"
    ts_md_path.write_text(render_md(ts), encoding="utf-8")
    print(f"产出 ts.md: {ts_md_path}")

    # 6. 摘要
    rules = ts["rules"]
    scenarios = set(r["scenario"] for r in rules.values() if r["scenario"])
    print(f"\n[完成] {len(rules)} 个规则, {len(scenarios)} 个场景, "
          f"{ts['meta']['field_count']['total']} 个字段(含审计)")


if __name__ == "__main__":
    main()
