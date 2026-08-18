"""扣分制评分：命中 golden = 100 分基准，按差异/断言失败扣分。

哲学（讨论定稿）：golden = 标准，命中是义务，不命中 = 发现问题 = 扣分。
不做归一化遮丑；分数是跨轮可比的刻度（baseline 存分数，稳定性报告看趋势）。

分类映射（谁失败/差什么 → 扣哪类分）：
- design 契约（business_key/规则集/load_mode）           → design_contract   -20
- 自洽性（DDL≠ts / SELECT漏字段 / 回退缺DROP / 视图列）    → self_consistency  -15
- 字段口径（SUM vs 裸列 / 引用错列 / 常量变值）           → field_caliber     -10
- 结构标准（表结构/数据流/命名/JOIN/GROUP_BY/field_targets）→ structure_std     -5
- 流程阶段挂                                              → pipeline_stage    -10
- 其他产物层断言                                          → artifact          -8
- 其他 design 层断言                                      → design_default    -6
- 其他 code 层断言                                        → code_default      -6

权重可用 checks.yaml 的 scoring: 段按案例覆盖（只写要改的键）。
无 golden 案例：不产生 golden 扣分项，其余照扣（断言层加权得分）。
"""

from __future__ import annotations

from pathlib import Path

import sys

_V2_DIR = Path(__file__).resolve().parent
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

DEFAULT_WEIGHTS: dict[str, int] = {
    "design_contract": 20,
    "self_consistency": 15,
    "field_caliber": 10,
    "structure_std": 5,
    "pipeline_stage": 10,
    "artifact": 8,
    "design_default": 6,
    "code_default": 6,
}

# design 层 detail 关键词 → 契约类（重）；其余 design 失败 → design_default
_DESIGN_CONTRACT_KEYWORDS = ("business_key", "规则集", "load_mode 契约", "incremental")
# code 层 detail 关键词 → 自洽类；其余 → code_default
_CODE_CONSISTENCY_KEYWORDS = ("字段覆盖契约",)
# artifacts 层 detail 关键词 → 自洽类；其余 → artifact
_ARTIFACT_CONSISTENCY_KEYWORDS = ("DDL列", "DDL类型", "DISTRIBUTE", "分布键", "I视图列", "回退SQL")
# golden 差异维度 → 分类
_GOLDEN_DIFF_MAP = [
    (("business_key", "规则集", "load_mode"), "design_contract"),
    (("DDL(", "SELECT缺失", "输出字段"), "self_consistency"),
    (("字段口径",), "field_caliber"),
    (("表结构", "规则数据流", "field_targets", "GROUP_BY", "JOIN表"), "structure_std"),
]


def _classify_check(layer: str, detail: str) -> str:
    """把一条失败断言归入扣分类别。"""
    if layer == "pipeline":
        return "pipeline_stage"
    if layer == "design":
        return "design_contract" if any(k in detail for k in _DESIGN_CONTRACT_KEYWORDS) else "design_default"
    if layer == "code":
        return "self_consistency" if any(k in detail for k in _CODE_CONSISTENCY_KEYWORDS) else "code_default"
    if layer == "artifacts":
        return "self_consistency" if any(k in detail for k in _ARTIFACT_CONSISTENCY_KEYWORDS) else "artifact"
    return "artifact"


def classify_golden_diff(diff: str) -> str:
    """把 golden compare 的一个差异维度归入扣分类别。"""
    for keywords, cat in _GOLDEN_DIFF_MAP:
        if any(k in diff for k in keywords):
            return cat
    return "structure_std"


def score_result(
    result,
    deliver: Path,
    case_dir: Path,
    weights_override: dict | None = None,
    golden_diffs: list[str] | None = None,
) -> dict:
    """对一次评测结果算分。

    Args:
        result: EvalResult（含各层断言与流程步骤）。
        deliver: 产出目录（golden 比对用）。
        case_dir: 案例目录（golden/ 在其下）。
        weights_override: checks.yaml scoring: 段的覆盖。
        golden_diffs: golden 层失败的差异维度列表；None 时按需自行比对。

    Returns:
        {"total": int, "deductions": [(类别, 扣分, 描述), ...], "has_golden": bool}
    """
    weights = dict(DEFAULT_WEIGHTS)
    if weights_override:
        weights.update({k: v for k, v in weights_override.items() if k in DEFAULT_WEIGHTS})

    deductions: list[tuple[str, int, str]] = []

    # 流程层
    for st in result.pipeline_steps or []:
        if st.status.value == "fail":
            deductions.append(("pipeline_stage", weights["pipeline_stage"],
                               f"流程挂: {st.step}"))

    # 断言层
    for layer, checks in result.layer_results.items():
        if layer == "golden":
            continue  # golden 单独算（按差异维度，不按断言条数）
        for c in checks:
            if c.status.value != "fail":
                continue
            cat = _classify_check(layer, c.detail)
            deductions.append((cat, weights[cat], c.detail.split("\n")[0][:80]))

    # golden 层：按差异维度逐项扣
    has_golden = False
    if golden_diffs is None:
        import golden

        goldens = golden.load_goldens(case_dir)
        if goldens:
            has_golden = True
            fp = golden.fingerprint(deliver)
            hit, diffs = golden.compare(fp, next(iter(goldens.values())))
            golden_diffs = [] if hit else diffs
    if golden_diffs:
        has_golden = True
        for d in golden_diffs:
            cat = classify_golden_diff(d)
            deductions.append((cat, weights[cat], f"golden差异: {d}"))

    total = max(0, 100 - sum(w for _, w, _ in deductions))
    return {"total": total, "deductions": deductions, "has_golden": has_golden}


def render_score(score: dict, prev_total: int | None = None) -> str:
    """总分块文本（嵌入评测报告）。"""
    lines = ["── 总分 ───────────────────────────────────────────"]
    prev = f"（上轮 {prev_total}）" if prev_total is not None else ""
    lines.append(f"  {score['total']}/100{prev}  无golden（仅断言层计分）"
                 if not score["has_golden"] else f"  {score['total']}/100{prev}")
    if score["deductions"]:
        lines.append("  扣分明细:")
        for cat, w, desc in score["deductions"][:10]:
            lines.append(f"    -{w:<3} [{cat}] {desc}")
        if len(score["deductions"]) > 10:
            lines.append(f"    … 其余 {len(score['deductions']) - 10} 项")
    else:
        lines.append("  ✅ 零扣分")
    return "\n".join(lines)
