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


def generate_gate1_summary(ts: dict, rs_input: dict = None) -> str:
    """从 ts.json 生成闸口①摘要文本。rs_input 可选——给了加翻译引用对账差异表。"""
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

    # 主键设计说明（如果调整过主键，展示出来）
    bk_design = design.get("business_key_design", {})
    if bk_design.get("adjusted"):
        input_key = bk_design.get("input_key", [])
        reason = bk_design.get("reason", "")
        lines.append(f"- **⚠️ 主键已调整**: 输入标注({', '.join(input_key)}) → 实际({', '.join(design.get('business_key', []))})")
        if reason:
            lines.append(f"  原因: {reason}")
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

    # 翻译引用对账（rs_input 提供时）：mapping 原文引用集 vs design_logic 引用集的差异——
    # 机器验掉"没变的"，人只审"变的"（丢引用=翻译事故高发区，差异表让人扫一眼就够）
    if rs_input:
        from sql_parse import diff_logic_refs
        raw_by_col = rs_input.get("_logic_refs") or {}
        diffs = []
        for code, rule in rules.items():
            for col, text in (rule.get("field_logics") or {}).items():
                missing = diff_logic_refs(raw_by_col.get(col), [str(text)])
                if missing:
                    diffs.append(f"- {code} 字段 {col}：原文引用了 {missing}，design_logic 未出现（疑似丢引用）")
        if diffs:
            lines.append("### ⚠️ 翻译引用对账（差异需人工确认）")
            lines.append("")
            lines.extend(diffs)
            lines.append("")
        else:
            lines.append("- **翻译引用对账**: 原文引用全部覆盖，无差异")
            lines.append("")

    lines.append("请选择：")
    lines.append("- ✅ 确认设计，进入编码")
    lines.append("- ✏️ 需要修改（说明哪里要改）")
    lines.append("- ❌ 放弃")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="闸口①摘要生成器（从 ts.json 直接生成）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rs", default="", help="rs_input.json 路径（可选，加了出翻译引用对账差异表）")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)

    rs_input = None
    if args.rs and Path(args.rs).exists():
        try:
            rs_input = json.loads(Path(args.rs).read_text(encoding="utf-8"))
        except Exception:
            rs_input = None  # 读不了就跳过对账段，不挡闸口

    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    print(generate_gate1_summary(ts, rs_input))


if __name__ == "__main__":
    main()
