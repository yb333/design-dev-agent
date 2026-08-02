#!/usr/bin/env python3
"""
TS 规则切片: ts.json --rule R0001 → 单个规则的 YAML

coder agent 不读整个 ts.json（大表 300+字段会上下文爆炸），
而是调本脚本拿自己那个规则的切片。

切片内容（coder 写 SELECT 需要的全部信息）：
- 规则基本信息（rule_code/name/target_table/design_intent）
- 字段列表（target_field/field_type/transform_type/source_fields/design_logic）
- 关联策略（joins/join_safety）
- 粒度（grain）
- CTE（如有）
- 审计字段模板（全局，固定4个）
- 业务主键（全局，供参考）

用法:
  python slice_ts.py --ts ts.json --rule R0001
  python slice_ts.py --ts ts.json --rule R0001 --output R0001_slice.yaml
"""

import sys
import json
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def slice_rule(ts: dict, rule_code: str) -> dict:
    """从 ts.json 切出单个规则的信息 + 需要的全局信息。"""
    rules = ts.get("rules", {})
    if rule_code not in rules:
        available = list(rules.keys())
        raise ValueError(
            f"规则 '{rule_code}' 不存在。可用规则: {available}"
        )

    rule = rules[rule_code]
    design = ts.get("design", {})

    # 组装切片
    return {
        # 规则基本信息
        "rule_code": rule_code,
        "rule_name": rule.get("rule_name", ""),
        "target_table": rule.get("target_table", ""),
        "is_view_step": rule.get("is_view_step", False),
        "scenario": rule.get("scenario", ""),
        "exec_sequence": rule.get("exec_sequence", 1),
        "design_intent": rule.get("design_intent", ""),

        # 关联策略（coder 写 FROM/JOIN 用）
        "source_tables": rule.get("source_tables", []),
        "joins": rule.get("joins", []),
        "join_safety": rule.get("join_safety", []),

        # 粒度变化
        "grain": rule.get("grain", {}),

        # CTE
        "ctes": rule.get("ctes", []),

        # ★ 字段列表（coder 写 SELECT 的核心依据）
        # 每个字段的 design_logic 是自然语言口径，coder 翻译成 SQL
        "fields": rule.get("fields", []),
        "field_count": rule.get("field_count", 0),

        # 全局信息（coder 需要参考的）
        "_global": {
            # 审计字段模板（固定4个，coder 写 SELECT 时要带上审计字段赋值）
            "audit_fields": design.get("audit_fields", {}),
            # 业务主键（coder 写 GROUP BY 时参考，确保不发散）
            "business_key": design.get("business_key", []),
            # 分布键（参考）
            "distribution_key": design.get("distribution_key", []),
            # 目标表 schema（从 meta 取）
            "target_schema": ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", ""),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="TS 规则切片: 从 ts.json 切出单个规则的 YAML（给 coder 读）"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    parser.add_argument("--output", default="", help="输出 YAML 路径（默认打印到 stdout）")
    args = parser.parse_args()

    # 读 ts.json
    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 切片
    try:
        sliced = slice_rule(ts, args.rule)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出
    yaml_text = yaml.dump(sliced, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        print(f"切片产出: {out}", file=sys.stderr)
        print(f"规则: {args.rule}, 字段数: {sliced['field_count']}", file=sys.stderr)
    else:
        print(yaml_text)


if __name__ == "__main__":
    main()
