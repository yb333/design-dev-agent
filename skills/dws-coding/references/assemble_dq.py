#!/usr/bin/env python3
"""
DQ 检查 SQL 生成器：从 ts.json 生成标准 DQ 检查 SQL 到 dq/

标准 DQ（每张目标表都有）：
1. 业务主键唯一性
2. 审计字段非空
3. 记录数合理性

定制 DQ（ts.json 的 dq_rules 非空时）：留占位，由 coder 单独产 SQL。

用法:
  python assemble_dq.py --ts ts.json --outdir dq/
"""

import sys
import json
import argparse
from pathlib import Path


def generate_dq_sql(ts: dict) -> dict[str, str]:
    """从 ts.json 生成标准 DQ 检查 SQL。

    返回 {文件名: SQL内容}。
    """
    design = ts.get("design", {})
    audit_fields = design.get("audit_fields", {})
    business_key = design.get("business_key", [])
    rules = ts.get("rules", {})
    meta = ts.get("meta", {})
    target_table = meta.get("target", {}).get("f_table", {}).get("table", "")

    result = {}

    # 只给目标 F表生成 DQ（中间表不需要 DQ）
    for code, rule in rules.items():
        rule_target = rule.get("target_table", "")
        _, table = (rule_target.split(".", 1) + [""])[:2] if "." in rule_target else ("", rule_target)

        # 只给 F表（非中间表、非视图）生成 DQ
        is_f_table = table.endswith("_f") or rule_target == target_table
        is_tmp = "tmp" in table.lower()
        if is_tmp or rule.get("is_view_step", False):
            continue
        if not is_f_table and rule_target != target_table:
            continue

        full_table = rule_target if "." in rule_target else f"{meta.get('target',{}).get('f_table',{}).get('schema','')}.{rule_target}"
        if not full_table or "." not in full_table:
            continue

        lines = []
        lines.append(f"-- ============================================================")
        lines.append(f"-- DQ 检查: {full_table}")
        lines.append(f"-- 规则: {code}")
        lines.append(f"-- ============================================================")
        lines.append("")

        # DQ-1: 业务主键唯一性
        if business_key:
            key_cols = ", ".join(business_key)
            lines.append(f"-- DQ-1: 业务主键唯一性（键: {key_cols}）")
            lines.append(f"-- 期望: 0 行（无重复）")
            lines.append(f"SELECT {key_cols}, COUNT(*) AS cnt")
            lines.append(f"FROM {full_table}")
            lines.append(f"GROUP BY {key_cols}")
            lines.append(f"HAVING COUNT(*) > 1;")
            lines.append("")

        # DQ-2: 审计字段非空
        lines.append(f"-- DQ-2: 审计字段非空")
        lines.append(f"-- 期望: 每个查询 0 行（无空值）")
        for aname in audit_fields:
            lines.append(f"SELECT COUNT(*) AS null_count_{aname}")
            lines.append(f"FROM {full_table}")
            lines.append(f"WHERE {aname} IS NULL;")
            lines.append("")

        # DQ-3: 记录数合理性
        lines.append(f"-- DQ-3: 记录数合理性")
        lines.append(f"-- 期望: count > 0（表不为空）")
        lines.append(f"SELECT COUNT(*) AS total_count")
        lines.append(f"FROM {full_table};")
        lines.append("")

        # 定制 DQ 占位（ts.json 的 dq_rules）
        dq_rules = ts.get("dq_rules", [])
        if dq_rules:
            lines.append(f"-- ============================================================")
            lines.append(f"-- 定制 DQ（来自 ts.json dq_rules，{len(dq_rules)} 条）")
            lines.append(f"-- ⚠️ 以下为设计意图，SQL 由 coder 单独产出")
            lines.append(f"-- ============================================================")
            for dq in dq_rules:
                rid = dq.get("rule_id", "")
                rname = dq.get("rule_name", "")
                ctype = dq.get("check_type", "")
                target = dq.get("target", "")
                threshold = dq.get("threshold", "")
                lines.append(f"-- {rid}: {rname} (类型: {ctype}, 对象: {target}, 阈值: {threshold})")
                lines.append(f"-- TODO: coder 生成 DQ SQL")
                lines.append("")

        filename = f"dq_{table}.sql"
        result[filename] = "\n".join(lines)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="DQ 检查 SQL 生成器：从 ts.json 生成标准 DQ 到 dq/"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--outdir", required=True, help="DQ 输出目录")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    dqs = generate_dq_sql(ts)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if dqs:
        for filename, content in dqs.items():
            (outdir / filename).write_text(content, encoding="utf-8")
            print(f"  ✓ dq/{filename}")
        print(f"\n[完成] 生成 {len(dqs)} 个 DQ 检查文件")
    else:
        # 即使没有目标 F表，也建空目录标记
        print("[完成] 无目标 F表，未生成 DQ 文件")


if __name__ == "__main__":
    main()
