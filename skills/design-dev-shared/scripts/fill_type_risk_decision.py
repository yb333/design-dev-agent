#!/usr/bin/env python3
"""
类型风险决策填值器：把用户决策填进 precheck 生成的骨架文件。

★ 解决什么问题：
   pipe 命令让 agent 手写 type_risk_decision.yaml（中文 key + 嵌套结构 + 精确枚举），
   容易写错（key 名/缩进/枚举值任一不对就 precheck 报错重跑）。
   本脚本让 agent 只传决策值（命令行参数），脚本负责安全地填进骨架。

★ 工作方式：
   读现有骨架（precheck 的 _generate_type_risk_skeleton 产出的），
   只填 批量处置策略 和每个字段的 处置/原因，不动字段清单。
   字段清单一致性由 precheck 自己保证（骨架是它生成的）。

★ 合法枚举值（脚本校验，错了当场报）：
   批量处置策略：加安全处理 | 不加
   处置：转换 | 不加 | 返源端

用法:
  # 只填批量策略（无跨大类字段时）
  python fill_type_risk_decision.py --decision type_risk_decision.yaml --batch-strategy "加安全处理"

  # 填批量策略 + 跨大类字段决策
  python fill_type_risk_decision.py --decision type_risk_decision.yaml \\
    --batch-strategy "加安全处理" \\
    --field-decisions 'remark:转换,biz_date:返源端' \\
    --reasons 'biz_date:源端建议改date类型'

退出码: 0=成功, 1=枚举值非法/字段不匹配, 2=文件错误
"""

import sys
import re
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# 合法枚举值（和 precheck.py 的 BATCH_OPTIONS / 处置选项保持一致）
BATCH_OPTIONS = {"加安全处理", "不加"}
FIELD_OPTIONS = {"转换", "不加", "返源端"}


def parse_kv_list(s: str) -> dict[str, str]:
    """解析 'k1:v1,k2:v2' 格式为 dict。值里的逗号用转义暂不支持（reasons 一般不含逗号）。"""
    if not s or not s.strip():
        return {}
    result = {}
    for pair in s.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"格式错误，应为 字段:值，实际 '{pair}'")
        k, v = pair.split(":", 1)
        result[k.strip()] = v.strip()
    return result


def fill_decision(decision_path: Path, batch_strategy: str = "",
                  field_decisions: dict = None, reasons: dict = None) -> str:
    """读骨架、填值、返回新内容。

    Args:
        decision_path: 骨架文件路径
        batch_strategy: 批量处置策略（加安全处理/不加），空则不填
        field_decisions: {字段名: 处置} 跨大类字段决策
        reasons: {字段名: 原因} 返源端时的原因

    返回: 填好后的 yaml 文本。
    异常: ValueError（枚举值非法/字段不匹配）。
    """
    field_decisions = field_decisions or {}
    reasons = reasons or {}

    if not decision_path.exists():
        raise ValueError(f"决策文件不存在: {decision_path}")

    dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    if not isinstance(dec, dict):
        raise ValueError("决策文件格式错误（顶层应为字典），请重跑 precheck 重新生成骨架")

    # 1. 填批量处置策略
    if batch_strategy:
        if batch_strategy not in BATCH_OPTIONS:
            raise ValueError(f"批量处置策略 '{batch_strategy}' 不合法，应为: {sorted(BATCH_OPTIONS)}")
        dec["批量处置策略"] = batch_strategy

    # 2. 填跨大类字段处置
    if field_decisions:
        ind_fields = dec.get("跨大类风险字段") or []
        if not ind_fields:
            raise ValueError("决策文件无跨大类风险字段，但传了 --field-decisions")
        # 骨架里的字段清单
        skeleton_cols = {item.get("目标字段", "") for item in ind_fields if isinstance(item, dict)}
        # 传入的决策字段
        decision_cols = set(field_decisions.keys())
        # 字段必须匹配（防 agent 传错字段名）
        unknown = decision_cols - skeleton_cols
        if unknown:
            raise ValueError(
                f"--field-decisions 里的字段不在决策清单中: {sorted(unknown)}。"
                f"清单内的字段: {sorted(skeleton_cols)}"
            )
        # 校验枚举值 + 填值
        for item in ind_fields:
            if not isinstance(item, dict):
                continue
            col = item.get("目标字段", "")
            if col in field_decisions:
                choice = field_decisions[col]
                if choice not in FIELD_OPTIONS:
                    raise ValueError(
                        f"字段 '{col}' 的处置 '{choice}' 不合法，应为: {sorted(FIELD_OPTIONS)}"
                    )
                item["处置"] = choice
                if choice == "返源端":
                    reason = reasons.get(col, "")
                    if not reason:
                        raise ValueError(f"字段 '{col}' 选了'返源端'但没传 --reasons，必填原因")
                    item["原因"] = reason

    return yaml.dump(dec, allow_unicode=True, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(
        description="类型风险决策填值器：把用户决策填进骨架（agent 不手写 yaml）"
    )
    parser.add_argument("--decision", required=True, help="决策文件路径（precheck 生成的骨架）")
    parser.add_argument("--batch-strategy", default="",
                        help="批量处置策略：加安全处理 | 不加")
    parser.add_argument("--field-decisions", default="",
                        help="跨大类字段处置，格式 '字段1:处置,字段2:处置'（处置：转换/不加/返源端）")
    parser.add_argument("--reasons", default="",
                        help="返源端原因，格式 '字段:原因'（选返源端的字段必填）")
    args = parser.parse_args()

    decision_path = Path(args.decision)

    # 解析 field-decisions / reasons
    try:
        field_decisions = parse_kv_list(args.field_decisions)
        reasons = parse_kv_list(args.reasons)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 填值
    try:
        filled = fill_decision(decision_path, args.batch_strategy, field_decisions, reasons)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 写回
    decision_path.write_text(filled, encoding="utf-8")

    # 摘要（stderr，不干扰 stdout）
    print(f"已填值: {decision_path}", file=sys.stderr)
    if args.batch_strategy:
        print(f"  批量处置策略: {args.batch_strategy}", file=sys.stderr)
    if field_decisions:
        for col, choice in field_decisions.items():
            extra = f"（原因: {reasons.get(col, '')}）" if choice == "返源端" and col in reasons else ""
            print(f"  {col}: {choice}{extra}", file=sys.stderr)


if __name__ == "__main__":
    main()
