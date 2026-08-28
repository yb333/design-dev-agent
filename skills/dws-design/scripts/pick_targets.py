#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick_targets——designer 的字段清单取料器（类比 coder 的 pick_fields）。

把 rs_input 里看得见的字段名誊成 design_decisions.yaml 的最终格式片段，
贴进去零调整（确定性输出：输入决定输出，无判断）。
查询模式（互斥）：
  --targets [--scenario X | --alias 别名 | --audit]   字段清单片段
  --rule --scenario X                                  完整规则条目（targets 预填，判断位留空）
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from dws_standards import STANDARD_AUDIT_NAMES

def _is_audit(fm):
    t = (fm.get("target_column") or "").lower()
    return t in STANDARD_AUDIT_NAMES


def load_fms(rs_path):
    rs = json.loads(Path(rs_path).read_text(encoding="utf-8"))
    return rs.get("field_mappings", [])


def pick(fms, scenario=None, alias=None, audit=False, exclude_audit=True):
    """确定性过滤：场景（scene_group 精确匹配）/ 来源别名 / 审计附否。"""
    out = []
    for fm in fms:
        tc = fm.get("target_column") or ""
        if not tc:
            continue
        if exclude_audit and _is_audit(fm) and not audit:
            continue
        if scenario and str(fm.get("scene_group") or "").strip() != scenario:
            continue
        if alias and (fm.get("source_alias") or "").strip().lower() != alias.lower():
            continue
        out.append(tc)
    # 去重保序
    seen, dedup = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup


def fmt_targets(targets):
    """field_targets 片段（yaml 最终格式，贴进规则条目零调整）。"""
    if not targets:
        return "field_targets: []"
    if sum(len(t) + 2 for t in targets) <= 100:
        return "field_targets: [" + ", ".join(targets) + "]"
    lines = ["field_targets:"]
    lines += [f"  - {t}" for t in targets]
    return "\n".join(lines)


RULE_SKELETON = """- rule_code: R0001
  rule_name: ""
  scenario: "{scenario}"
  exec_sequence: 1
  target_table: ""
  design_intent: ""
  load_mode: "truncate_table"
  write_condition: ""
  step_type: full
  target_role: target
  produces_for: []
  reads: []
  filter: ""
  {targets_block}
  field_logics: {{}}
  joins: []
  join_safety: []
  grain: {{input: "", output: "", change: ""}}"""


def main():
    ap = argparse.ArgumentParser(description="designer 字段清单取料器（输出 yaml 最终格式片段）")
    ap.add_argument("--rs", required=True, help="rs_input.json 路径")
    ap.add_argument("--targets", action="store_true", help="字段清单片段")
    ap.add_argument("--rule", action="store_true", help="完整规则条目骨架（判断位留空）")
    ap.add_argument("--scenario", default="", help="按场景过滤（mapping 分组列）")
    ap.add_argument("--alias", default="", help="按来源别名过滤（拆多步骤规则用）")
    ap.add_argument("--audit", action="store_true", help="附审计4字段（多步骤规则的 targets 需含）")
    args = ap.parse_args()

    fms = load_fms(args.rs)
    targets = pick(fms, scenario=args.scenario or None, alias=args.alias or None,
                   audit=args.audit)
    if not args.targets and not args.rule:
        args.targets = True
    if args.rule:
        blk = fmt_targets(targets)
        # 缩进对齐规则条目（targets 在条目内，2 空格层级）
        blk = "\n  ".join(blk.split("\n"))
        print(RULE_SKELETON.format(scenario=args.scenario, targets_block=blk))
    else:
        print(fmt_targets(targets))
    if not targets:
        print("# （无匹配字段——检查 --scenario/--alias 值）", file=sys.stderr)


if __name__ == "__main__":
    main()
