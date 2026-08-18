"""两级评分：致命项（及格门）+ 非致命项（只扣分）。

及格标准（用户定义）：结果准确、不影响交付——加工逻辑没错、字段全、
类型满足输入要求。及格 = 致命项零失败（不是分数阈值）；非致命项
（结构漂移/常量/精度）只扣分做趋势，不拦及格。

根因去重：同一根因只扣一次——契约断言已扣过的维度，golden 的同维度
差异只在报告展示证据，不重复计分。
"""

from __future__ import annotations

from pathlib import Path

import sys

_V2_DIR = Path(__file__).resolve().parent
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

DEFAULT_WEIGHTS: dict[str, int] = {
    "fatal": 20,          # 致命项单项（任一失败即不及格）
    "structure_std": 5,   # 表结构/命名/数据流/GROUP_BY/JOIN 漂移
    "caliber_const": 2,   # 口径常量差异（写法差异，人裁决）
    "type_precision": 2,  # 类型精度差异（基类型满足输入要求即可）
    "artifact": 8,        # 其他产物层断言失败
    "design_default": 6,  # 其他 design 层断言失败
    "code_default": 6,    # 其他 code 层断言失败
}

# 致命根因集合：任一出现 = 不及格
FATAL_ROOTS = {
    "pipeline",         # 流程没跑通
    "field_coverage",   # 字段不全（SELECT漏字段/DDL缺列/覆盖不全）
    "ddl_columns",      # DDL 列集合不符
    "ddl_type",         # DDL 基类型不符
    "type_input",       # ts 类型不符 mapping 输入要求
    "caliber_logic",    # 加工逻辑错（口径 refs/aggs 与 golden 不一致）
    "business_key",     # 主键契约错（粒度错）
    "load_mode",        # 写入模式契约错（清历史事故级）
    "rules",            # 规则集契约错
    "view_cols",        # I 视图缺列（交付物不完整）
}

# 断言失败 detail 关键词 → 根因（未命中的按层归 default）
_ASSERTION_ROOTS = [
    (("design", "business_key"), "business_key"),
    (("design", "规则集"), "rules"),
    (("design", "load_mode 契约"), "load_mode"),
    (("design", "类型不符输入要求"), "type_input"),
    (("artifacts", "DDL列"), "ddl_columns"),
    (("artifacts", "DDL类型"), "ddl_type"),
    (("artifacts", "I视图列"), "view_cols"),
    (("code", "字段覆盖契约"), "field_coverage"),
]

# golden 差异 → 根因
_GOLDEN_ROOTS = [
    (("business_key",), "business_key"),
    (("规则集",), "rules"),
    (("load_mode",), "load_mode"),
    (("DDL(列)",), "ddl_columns"),
    (("DDL(基类型)",), "ddl_type"),
    (("DDL(类型精度)",), "type_precision"),
    (("SELECT缺失", "输出字段"), "field_coverage"),
    (("口径逻辑",), "caliber_logic"),
    (("口径常量",), "caliber_const"),
    (("表结构", "规则数据流", "field_targets", "GROUP_BY", "JOIN表"), "structure_std"),
]


def _root_of_assertion(layer: str, detail: str) -> tuple[str, str]:
    """断言失败 → (根因, 扣分类别)。根因在 FATAL_ROOTS → 类别 fatal。"""
    for (ly, kw), root in _ASSERTION_ROOTS:
        if layer == ly and kw in detail:
            return root, "fatal" if root in FATAL_ROOTS else "structure_std"
    return f"{layer}_default", {
        "pipeline": "fatal", "artifacts": "artifact",
        "design": "design_default", "code": "code_default",
    }.get(layer, "artifact")


def _root_of_golden_diff(diff: str) -> tuple[str, str]:
    for kws, root in _GOLDEN_ROOTS:
        if any(k in diff for k in kws):
            return root, "fatal" if root in FATAL_ROOTS else root
    return "structure_std", "structure_std"


def score_result(
    result,
    deliver: Path,
    case_dir: Path,
    weights_override: dict | None = None,
    golden_diffs: list[str] | None = None,
) -> dict:
    """对一次评测结果算分（两级）。

    Returns:
        {"total", "deductions": [(类别, 扣分, 描述, 是否致命)],
         "fatal": [致命描述...], "passed": bool, "has_golden": bool}
    """
    weights = dict(DEFAULT_WEIGHTS)
    if weights_override:
        weights.update({k: v for k, v in weights_override.items() if k in DEFAULT_WEIGHTS})

    deductions: list[tuple[str, int, str, bool]] = []
    fatal_descs: list[str] = []
    deducted_roots: set[str] = set()

    # 流程层（致命）
    for st in result.pipeline_steps or []:
        if st.status.value == "fail":
            deductions.append(("fatal", weights["fatal"], f"流程挂: {st.step}", True))
            fatal_descs.append(f"流程挂: {st.step}")
            deducted_roots.add("pipeline")

    # 断言层
    for layer, checks in result.layer_results.items():
        if layer == "golden":
            continue
        for c in checks:
            if c.status.value != "fail":
                continue
            root, cat = _root_of_assertion(layer, c.detail)
            deductions.append((cat, weights[cat], c.detail.split("\n")[0][:80],
                               root in FATAL_ROOTS))
            if root in FATAL_ROOTS:
                fatal_descs.append(c.detail.split("\n")[0][:60])
            deducted_roots.add(root)

    # golden 层：按差异维度逐项扣；同根因已扣过（断言层）→ 只展示不重复扣
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
            root, cat = _root_of_golden_diff(d)
            if root in deducted_roots:
                continue  # 根因去重：断言层已扣，golden 只做证据展示
            deductions.append((cat, weights[cat], f"golden差异: {d[:80]}", root in FATAL_ROOTS))
            if root in FATAL_ROOTS:
                fatal_descs.append(f"golden差异: {d[:60]}")
            deducted_roots.add(root)

    total = max(0, 100 - sum(w for _, w, _, _ in deductions))
    return {
        "total": total,
        "deductions": deductions,
        "fatal": fatal_descs,
        "passed": not fatal_descs,
        "has_golden": has_golden,
    }


def render_score(score: dict, prev_total: int | None = None) -> str:
    """总分块文本（嵌入评测报告）。"""
    lines = ["── 总分 ───────────────────────────────────────────"]
    prev = f"（上轮 {prev_total}）" if prev_total is not None else ""
    if score["passed"]:
        lines.append(f"  ✔及格（交付安全）{score['total']}/100{prev}")
    else:
        lines.append(f"  ✘不及格 {score['total']}/100{prev}  致命项:")
        for f in score["fatal"][:6]:
            lines.append(f"     ✘ {f}")
        if len(score["fatal"]) > 6:
            lines.append(f"     … 其余 {len(score['fatal']) - 6} 项")
    if not score["has_golden"]:
        lines.append("  ⚠️ 无golden（致命④加工逻辑无参照，仅自洽兜底，及格含金量打折）")
    non_fatal = [d for d in score["deductions"] if not d[3]]
    if non_fatal:
        lines.append("  非致命扣分（不拦及格，看趋势）:")
        for cat, w, desc, _ in non_fatal[:8]:
            lines.append(f"    -{w:<3} [{cat}] {desc}")
    elif not score["fatal"]:
        lines.append("  ✅ 零扣分")
    return "\n".join(lines)
