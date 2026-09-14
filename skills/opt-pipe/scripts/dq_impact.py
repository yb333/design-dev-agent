#!/usr/bin/env python3
"""DQ 影响分析（opt 场景，2026-09-14 DQ 拆分补环）：变更集 ∩ baseline DQ 锚定 → 重做清单。

确定性集合运算（零 AI）：优化改了什么 → 哪些 DQ 检查受影响 → producer 只重做受影响条目
（未受影响的原样继承）。两条命中路径：
  ① 变更目标字段 ∩ dq.anchored_fields（改字段口径 → 锚定该字段的检查失效）
  ② 变更来源表 ∩ dq.compare_sources（新增/变更来源 → 对比式的比对对象变了）
外加：新增字段建议补 DQ（RS 有对应需求时——信息性提示不强制）。

用法（步骤 3.5，precheck_opt 后跑，结果进闸口①' 材料）:
  python dq_impact.py --baseline-dq {arc_tmp}/dq.json \
      --change-request {build}/_internal/change_request.json [--output {build}/_internal/dq_impact.md]

退出码: 0=有/无受影响均正常产出清单；2=文件缺失（baseline 无 DQ = 空清单不算错——
存量资产可能还是旧形态 dq_rules 在 ts 里，此时报告"无可分析对象，DQ 维持现状"）。
"""

import sys
import json
import argparse
from pathlib import Path


def _short(name: str) -> str:
    return str(name or "").rsplit(".", 1)[-1].strip().lower()


def _norm_field(name: str) -> str:
    return str(name or "").strip().lower()


def analyze(dq_rules: list, changed_fields: list, changed_sources: list) -> dict:
    """纯函数：受影响条目分析。changed_fields=变更目标字段短名集；changed_sources=变更来源表短名集。"""
    fset = {_norm_field(f) for f in changed_fields if str(f).strip()}
    tset = {_short(t) for t in changed_sources if str(t).strip()}
    hits, untouched = [], []
    for r in dq_rules or []:
        idx = r.get("idx") or (r.get("_idx") or 0)
        anchor = {_norm_field(a) for a in (r.get("anchored_fields") or [])}
        # 旧形态兼容（ts.dq_rules 无锚定声明）：从 violation_condition 粗提目标字段引用兜底
        if not anchor and r.get("violation_condition"):
            anchor = {_norm_field(c) for c in _guess_anchors(r.get("violation_condition"))}
        comps = {_short(s) for s in (r.get("compare_sources") or [])}
        reasons = []
        hit_fields = sorted(anchor & fset)
        if hit_fields:
            reasons.append(f"锚定字段被变更: {hit_fields}")
        hit_srcs = sorted(comps & tset)
        if hit_srcs:
            reasons.append(f"比对来源被变更: {hit_srcs}")
        entry = {"idx": idx, "rule_name": r.get("rule_name") or "",
                 "check_type": r.get("check_type") or "", "mode": r.get("mode") or "assertion",
                 "reasons": reasons}
        (hits if reasons else untouched).append(entry)
    return {"changed_fields": sorted(fset), "changed_sources": sorted(tset),
            "rebuild": hits, "keep": untouched}


def _guess_anchors(vc: str) -> list:
    """旧形态兜底：从 violation_condition 提取 别名.字段 的字段段（粗提，无登记处对照）。"""
    import re
    return [m.group(1) for m in re.finditer(r"[A-Za-z_]\w*\.\s*([A-Za-z_]\w*)", vc or "")]


def load_dq_rules_anywhere(baseline_dq: Path) -> list:
    """读 baseline DQ 清单：dq.json 优先；旧形态读 ts.json 的 dq_rules。两处无=空。"""
    if baseline_dq.name == "dq.json":
        if baseline_dq.exists():
            return json.loads(baseline_dq.read_text(encoding="utf-8")).get("rules") or []
        return []
    # 传了 ts.json 路径（旧形态）
    if baseline_dq.exists():
        return json.loads(baseline_dq.read_text(encoding="utf-8")).get("dq_rules") or []
    return []


def render_md(result: dict, has_baseline_dq: bool) -> str:
    lines = ["# DQ 影响分析（确定性集合运算——producer 只重做受影响条目）", ""]
    if not has_baseline_dq:
        lines.append("> baseline 无 DQ（dq.json/dq_rules 均无）——本资产无存量检查可影响；"
                     "RS 本次变更若新增 DQ 需求，按 new-pipe 流程 producer 新设计。")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"- 变更目标字段：{', '.join(result['changed_fields']) or '（无）'}")
    lines.append(f"- 变更来源表：{', '.join(result['changed_sources']) or '（无）'}")
    lines.append("")
    if result["rebuild"]:
        lines.append(f"## 需重做（{len(result['rebuild'])} 条——锚定/比对来源被变更）")
        lines.append("")
        for r in result["rebuild"]:
            lines.append(f"- DQ{r['idx']}（{r['rule_name']}，{r['mode']}）: {'；'.join(r['reasons'])}")
        lines.append("")
    else:
        lines.append("## 无受影响条目——DQ 全量原样继承（producer 不起调）")
        lines.append("")
    if result["keep"]:
        lines.append(f"## 原样继承（{len(result['keep'])} 条）")
        lines.append("")
        for r in result["keep"]:
            lines.append(f"- DQ{r['idx']}（{r['rule_name']}）")
        lines.append("")
    return "\n".join(lines)


def _collect_change_sets(change_request: dict):
    """从 change_request 提取变更字段/来源集（键形态按 preprocess_opt 的产出）。"""
    fields = []
    for f in (change_request.get("fields") or []):
        # 形态兼容：{target_column|column|field}
        fields.append(f.get("target_column") or f.get("column") or f.get("field") or "")
    sources = []
    for s in (change_request.get("new_sources") or change_request.get("sources") or []):
        sources.append(s.get("table") or s.get("source_table") or str(s))
    return [f for f in fields if f], [s for s in sources if s]


def main():
    parser = argparse.ArgumentParser(description="DQ 影响分析（变更集∩锚定/比对来源 → 重做清单）")
    parser.add_argument("--baseline-dq", required=True,
                        help="baseline dq.json 路径（旧资产可传 archive/ts.json 读 dq_rules）")
    parser.add_argument("--change-request", required=True, help="change_request.json 路径")
    parser.add_argument("--output", default="", help="分析报告落盘路径（默认 stdout）")
    args = parser.parse_args()

    dq_path = Path(args.baseline_dq)
    cr_path = Path(args.change_request)
    if not cr_path.exists():
        print(f"错误: change_request.json 不存在: {cr_path}", file=sys.stderr)
        sys.exit(2)
    try:
        cr = json.loads(cr_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误: change_request 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    dq_rules = load_dq_rules_anywhere(dq_path)
    # 旧形态读 ts 时 idx 缺失——按数组序补
    dq_rules = [{**r, "idx": r.get("idx") or i} for i, r in enumerate(dq_rules, 1)]
    changed_fields, changed_sources = _collect_change_sets(cr)
    result = analyze(dq_rules, changed_fields, changed_sources)
    text = render_md(result, has_baseline_dq=bool(dq_rules))

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"影响分析: {out}")
    else:
        print(text)
    n = len(result["rebuild"])
    print(f"DQ 影响分析: 需重做 {n} 条 / 原样继承 {len(result['keep'])} 条", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
