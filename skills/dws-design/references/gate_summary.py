#!/usr/bin/env python3
"""
闸口摘要生成器：从 ts.json 直接生成闸口①（设计确认）的摘要文本。

不需要 AI 提取——表名/规则数/字段统计/规则概览全是 ts.json 里的固定值。
command 在闸口①时调本脚本，拿输出展示给人。

用法:
  python gate_summary.py --ts ts.json
"""

import sys
import json
import argparse
from pathlib import Path


def generate_gate1_summary(ts: dict) -> str:
    """从 ts.json 生成闸口①摘要文本。"""
    meta = ts.get("meta", {})
    target = meta.get("target", {})
    design = ts.get("design", {})
    rules = ts.get("rules", {})
    fc = meta.get("field_count", {})

    lines = []
    lines.append("## 设计完成，请确认方向")
    lines.append("")

    # 概述
    f_table = target.get("f_table", {})
    lines.append("### 设计摘要")
    lines.append(f"- **目标表**: {f_table.get('schema','')}.{f_table.get('table','')}（{f_table.get('cn','')}）")
    lines.append(f"- **规则数**: {len(rules)} 个")
    lines.append(f"- **场景数**: {len(set(r.get('scenario','') for r in rules.values() if r.get('scenario')))} 个")
    lines.append(f"- **字段统计**: 业务 {fc.get('business',0)} + 审计 {fc.get('audit',0)} = 总计 {fc.get('total',0)}")
    lines.append("")

    # 分段决策
    comp = design.get("complexity_analysis", {})
    seg = comp.get("segmentation_decision", "")
    if seg:
        lines.append(f"- **分段决策**: {seg}")
        reason = comp.get("segmentation_reason", "")
        if reason:
            lines.append(f"  - 理由: {reason[:100]}")
        lines.append("")

    # 规则概览
    lines.append("### 规则概览")
    lines.append("")
    lines.append("| 规则 | 名称 | 产出表 | 字段数 | 设计意图 |")
    lines.append("|------|------|--------|--------|----------|")
    for code, rule in rules.items():
        name = rule.get("rule_name", "")
        target_table = rule.get("target_table", "")
        field_count = rule.get("field_count", 0)
        intent = rule.get("design_intent", "")
        # 设计意图截断
        if len(intent) > 60:
            intent = intent[:60] + "..."
        lines.append(f"| {code} | {name} | `{target_table}` | {field_count} | {intent} |")
    lines.append("")

    # 关联安全要点
    lines.append("### 关联安全要点")
    lines.append("")
    has_safety = False
    for code, rule in rules.items():
        for js in rule.get("join_safety", []):
            if not js.get("join_key_unique", True):
                table = js.get("table", "")
                strategy = js.get("strategy", "")
                reason = js.get("reason", "")
                if reason and len(reason) > 50:
                    reason = reason[:50] + "..."
                lines.append(f"- {code} → `{table}`: **{strategy}** — {reason}")
                has_safety = True
    if not has_safety:
        lines.append("- 所有关联键唯一，无需特殊对齐策略")
    lines.append("")

    # 审计字段来源
    supplemented = design.get("audit_supplemented", [])
    if supplemented:
        lines.append(f"- **审计字段**: RS 未提供 {len(supplemented)} 个（{'、'.join(supplemented)}），已自动补充")
    else:
        lines.append("- **审计字段**: 全部来自 RS/mapping")
    lines.append("")

    lines.append("请选择：")
    lines.append("- ✅ 确认设计，进入编码")
    lines.append("- ✏️ 需要修改（说明哪里要改）")
    lines.append("- ❌ 放弃")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="闸口①摘要生成器（从 ts.json 直接生成）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)

    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    print(generate_gate1_summary(ts))


if __name__ == "__main__":
    main()
