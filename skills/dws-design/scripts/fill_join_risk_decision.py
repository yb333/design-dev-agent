#!/usr/bin/env python3
"""
关联键类型决策填值器：把用户决策填进 precheck 生成的骨架文件。

★ 解决什么问题（同 fill_type_risk_decision）：
   pipe 命令让 agent 手写 join_type_decision.yaml（中文 key + 枚举值），容易写错。
   本脚本让 agent 只传决策值（命令行参数），脚本负责安全地填进骨架。

★ 工作方式：
   读现有骨架（precheck 的 _generate_join_risk_skeleton 产出的），
   只填每对的 处置/原因，不动字段清单。清单一致性由 precheck 自己保证。

★ 合法枚举值（脚本校验，错了当场报）：
   处置：转换 | 改关联键 | 接受

用法:
  python fill_join_risk_decision.py --decision join_type_decision.yaml \\
    --pair-decisions 'a.prod_code = b.prod_id=>接受' \\
    --reasons 'a.prod_code = b.prod_id=>业务确认就这么关联'

  （--pair-decisions / --reasons 可重复传多对；分隔符 '=>'，条件原样含空格）

退出码: 0=成功, 1=枚举值非法/条件不匹配, 2=文件错误
"""

import sys
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# 合法枚举值（和 precheck.py 的 JOIN_RISK_OPTIONS 保持一致）
PAIR_OPTIONS = {"转换", "改关联键", "接受"}


def parse_arrow_items(items: list[str]) -> dict[str, str]:
    """解析 ['条件=>值', ...] 为 {条件: 值}。分隔符 '=>'——关联条件含 '=' 和空格，
    用 => 不会和条件内容冲突。"""
    out: dict[str, str] = {}
    for it in items or []:
        if "=>" not in it:
            print(f"错误: '{it}' 缺分隔符 '=>'（格式：条件=>处置）", file=sys.stderr)
            sys.exit(1)
        k, v = it.rsplit("=>", 1)
        k, v = k.strip(), v.strip()
        if not k or not v:
            print(f"错误: '{it}' 键或值为空", file=sys.stderr)
            sys.exit(1)
        out[k] = v
    return out


def fill(decision_path: Path, pair_decisions: dict[str, str],
         reasons: dict[str, str]) -> int:
    """把决策填进骨架。返回 0=成功，1=条件不匹配/枚举非法。"""
    try:
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"错误: 决策文件读不了({decision_path}): {e}", file=sys.stderr)
        return 2
    if not isinstance(dec, dict) or not isinstance(dec.get("关联风险对"), list):
        print("错误: 决策文件格式不对（应含 关联风险对 列表——先跑 precheck 生成骨架）", file=sys.stderr)
        return 2

    known_conds = [it.get("关联条件", "") for it in dec["关联风险对"] if isinstance(it, dict)]
    unknown = set(pair_decisions) - set(known_conds)
    if unknown:
        print(f"错误: 这些条件不在骨架里（骨架条件: {known_conds}）: {sorted(unknown)}", file=sys.stderr)
        return 1

    bad = {c: v for c, v in pair_decisions.items() if v not in PAIR_OPTIONS}
    if bad:
        print(f"错误: 枚举值非法 {bad}（应为：{'/'.join(sorted(PAIR_OPTIONS))}）", file=sys.stderr)
        return 1

    for it in dec["关联风险对"]:
        if not isinstance(it, dict):
            continue
        cond = it.get("关联条件", "")
        if cond in pair_decisions:
            it["处置"] = pair_decisions[cond]
        if cond in reasons:
            it["原因"] = reasons[cond]

    decision_path.write_text(
        yaml.safe_dump(dec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"已填 {len(pair_decisions)} 对处置 → {decision_path}（重跑 precheck 放行）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="关联键类型决策填值器（pipe 编排用，不手写 yaml）")
    parser.add_argument("--decision", required=True, help="join_type_decision.yaml 路径")
    parser.add_argument("--pair-decisions", action="append", default=[],
                        help="条件=>处置（可重复；处置：转换/改关联键/接受）")
    parser.add_argument("--reasons", action="append", default=[],
                        help="条件=>原因（可重复；选改关联键/接受时建议填）")
    args = parser.parse_args()

    if not args.pair_decisions and not args.reasons:
        parser.error("至少传一个 --pair-decisions")

    rc = fill(
        Path(args.decision),
        parse_arrow_items(args.pair_decisions),
        parse_arrow_items(args.reasons),
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
