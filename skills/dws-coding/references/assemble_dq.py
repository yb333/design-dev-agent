#!/usr/bin/env python3
"""
DQ 检查 SQL 生成器：从 ts.json 生成 DQ 检查 SQL 到 dq/

核心逻辑：
- RS（dq_rules）提供的 DQ → 按规则生成 SQL（RS 有就用 RS 的，不重复生成）
- 标准检查只补 RS 没覆盖的（主键唯一/审计非空/记录数）

去重规则（避免和 RS 重复）：
- RS 有"重复数据检查"/"唯一性" → 不再标准生成主键唯一
- RS 有"空值检查"/"非空" 且覆盖了审计字段 → 不再标准生成审计非空

用法:
  python assemble_dq.py --ts ts.json --outdir dq/
"""

import sys
import json
import argparse
from pathlib import Path


def _has_duplicate_check(dq_rules: list) -> bool:
    """RS 的 dq_rules 里有没有重复数据/唯一性检查"""
    for dq in dq_rules:
        ctype = (dq.get("check_type", "") + dq.get("rule_name", "")).lower()
        if any(k in ctype for k in ["重复", "唯一", "unique", "duplicate"]):
            return True
    return False


def _has_null_check(dq_rules: list) -> bool:
    """RS 的 dq_rules 里有没有空值/非空检查"""
    for dq in dq_rules:
        ctype = (dq.get("check_type", "") + dq.get("rule_name", "")).lower()
        if any(k in ctype for k in ["空值", "非空", "null", "not null"]):
            return True
    return False


def _extract_field_name(text: str) -> str:
    """从规则名称/描述中提取字段名（英文字段名）。

    如 'order_id非空检查' → 'order_id'
    如 'del_flag值域检查' → 'del_flag'
    如 '金额不能为负' → ''（中文描述提取不到英文字段名）
    """
    import re
    m = re.search(r'[a-z_][a-z0-9_]*', text.lower())
    return m.group(0) if m else ""


def generate_dq_for_table(full_table: str, code: str, business_key: list,
                          audit_fields: dict, dq_rules: list) -> str:
    """为一张表生成 DQ SQL。

    优先用 RS 的 dq_rules，标准检查只补 RS 没覆盖的。
    """
    lines = []
    lines.append(f"-- ============================================================")
    lines.append(f"-- DQ 检查: {full_table}")
    lines.append(f"-- 规则: {code}")
    lines.append(f"-- ============================================================")
    lines.append("")

    # 判断 RS 有没有覆盖
    has_dup = _has_duplicate_check(dq_rules)
    has_null = _has_null_check(dq_rules)

    # === RS 提供的 DQ（按 check_type + target 结构化生成，不从描述猜） ===
    if dq_rules:
        lines.append(f"-- RS 提供的 DQ（{len(dq_rules)} 条）")
        lines.append("")
        for dq in dq_rules:
            rname = dq.get("rule_name", "")
            rdesc = dq.get("rule_desc", "")
            rtype = (dq.get("check_type", "") or "").lower()
            target = dq.get("target", "")
            threshold = dq.get("threshold", "")
            lines.append(f"-- [{rname}] 类型: {rtype}, 对象: {target}")

            # 按 check_type 精确分类生成 SQL
            # 唯一性检查
            if any(k in rtype for k in ["重复", "唯一", "duplicate", "uniqueness"]):
                key = business_key if business_key else ([target] if target else [])
                if not key:
                    lines.append(f"-- TODO: business_key 和 target 都为空，coder 补充唯一性检查字段")
                else:
                    key_cols = ", ".join(key)
                    lines.append(f"SELECT {key_cols}, COUNT(*) AS cnt")
                    lines.append(f"FROM {full_table}")
                    lines.append(f"GROUP BY {key_cols}")
                    lines.append(f"HAVING COUNT(*) > 1;")
                lines.append("")

            # 空值检查
            elif any(k in rtype for k in ["空值", "非空", "null"]):
                # target 是检查的字段名；如果没有，从 rule_name 提取
                field = target if target else _extract_field_name(rname)
                if field:
                    lines.append(f"SELECT COUNT(*) AS null_count_{field}")
                    lines.append(f"FROM {full_table}")
                    lines.append(f"WHERE {field} IS NULL;")
                else:
                    lines.append(f"-- TODO: 未提取到检查字段，coder 根据 '{rname}' 补充")
                lines.append("")

            # 值域检查（枚举值，如 del_flag 只能 Y/N）
            elif any(k in rtype for k in ["值域", "枚举", "value_range", "enum"]):
                field = target if target else _extract_field_name(rname)
                if field:
                    # threshold 通常是合法值列表，如 "Y,N"
                    if threshold:
                        vals = ", ".join([f"'{v.strip()}'" for v in threshold.split(",")])
                        lines.append(f"SELECT COUNT(*) AS invalid_count_{field}")
                        lines.append(f"FROM {full_table}")
                        lines.append(f"WHERE {field} NOT IN ({vals});")
                    else:
                        lines.append(f"-- TODO: 值域检查缺少 threshold（合法值列表），coder 补充")
                        lines.append(f"-- 检查字段: {field}")
                else:
                    lines.append(f"-- TODO: 未提取到检查字段，coder 根据 '{rname}' 补充")
                lines.append("")

            # 范围检查（数值范围，如金额 >= 0）
            elif any(k in rtype for k in ["范围", "range", "负"]):
                field = target if target else _extract_field_name(rname)
                if field:
                    lines.append(f"SELECT COUNT(*) AS invalid_count_{field}")
                    lines.append(f"FROM {full_table}")
                    lines.append(f"WHERE {field} < 0;")
                else:
                    lines.append(f"-- TODO: 未提取到检查字段，coder 根据 '{rname}' 补充")
                lines.append("")

            else:
                # 未知类型——留占位由 coder 补
                lines.append(f"-- TODO: coder 根据规则 '{rname}'（类型: {rtype}, 对象: {target}）生成 DQ SQL")
                lines.append("")

    # === 标准检查（只补 RS 没覆盖的） ===
    lines.append(f"-- 标准检查（补 RS 未覆盖的）")
    lines.append("")

    # 标准检查1: 主键唯一（RS 没有重复检查时才生成）
    if not has_dup and business_key:
        key_cols = ", ".join(business_key)
        lines.append(f"-- 主键唯一性（键: {key_cols}）")
        lines.append(f"SELECT {key_cols}, COUNT(*) AS cnt")
        lines.append(f"FROM {full_table}")
        lines.append(f"GROUP BY {key_cols}")
        lines.append(f"HAVING COUNT(*) > 1;")
        lines.append("")

    # 标准检查2: 审计字段非空（RS 没有空值检查时才生成）
    if not has_null:
        lines.append(f"-- 审计字段非空")
        for aname in audit_fields:
            lines.append(f"SELECT COUNT(*) AS null_count_{aname}")
            lines.append(f"FROM {full_table}")
            lines.append(f"WHERE {aname} IS NULL;")
        lines.append("")

    # 标准检查3: 记录数（RS 不会覆盖这个，总是生成）
    lines.append(f"-- 记录数合理性")
    lines.append(f"SELECT COUNT(*) AS total_count")
    lines.append(f"FROM {full_table};")
    lines.append("")

    return "\n".join(lines)


def generate_dq_sql(ts: dict) -> dict[str, str]:
    """从 ts.json 生成 DQ 检查 SQL。"""
    design = ts.get("design", {})
    audit_fields = design.get("audit_fields", {})
    business_key = design.get("business_key", [])
    rules = ts.get("rules", {})
    meta = ts.get("meta", {})
    target_table = meta.get("target", {}).get("f_table", {}).get("table", "")
    f_schema = meta.get("target", {}).get("f_table", {}).get("schema", "")
    dq_rules = ts.get("dq_rules", [])

    result = {}

    for code, rule in rules.items():
        rule_target = rule.get("target_table", "")
        _, table = (rule_target.split(".", 1) + [""])[:2] if "." in rule_target else ("", rule_target)

        # 只给目标表生成 DQ（不给中间表/视图）
        # 判断方式：target_table 等于 meta.target.f_table，或不含 tmp
        is_tmp = "tmp" in table.lower()
        is_view = rule.get("is_view_step", False)
        is_target = (table == target_table or rule_target == target_table
                     or (target_table and table.endswith(target_table)))
        if is_tmp or is_view:
            continue
        if not is_target:
            continue

        full_table = rule_target if "." in rule_target else f"{f_schema}.{rule_target}"
        if "." not in full_table:
            continue

        filename = f"dq_{table}.sql"
        result[filename] = generate_dq_for_table(full_table, code, business_key, audit_fields, dq_rules)

    return result


def main():
    parser = argparse.ArgumentParser(description="DQ 检查 SQL 生成器")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--outdir", required=True, help="DQ 输出目录")
    args = parser.parse_args()

    ts = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    dqs = generate_dq_sql(ts)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if dqs:
        for filename, content in dqs.items():
            (outdir / filename).write_text(content, encoding="utf-8")
            print(f"  ✓ dq/{filename}")
        print(f"\n[完成] 生成 {len(dqs)} 个 DQ 检查文件")
    else:
        print("[完成] 无目标 F表，未生成 DQ 文件")


if __name__ == "__main__":
    main()
