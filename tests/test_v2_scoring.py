"""扣分制评分测试：分类映射 / 算分 / 权重覆盖 / 呈现。"""

import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import scoring
from engine import EvalResult, PipelineStepResult
from validators.base import CheckResult, CheckStatus


def _mk_result(checks: list[tuple[str, str]], steps: list[tuple[str, str]] | None = None) -> EvalResult:
    """checks: [(layer, detail)] 全 FAIL；steps: [(name, status)]。"""
    r = EvalResult(case_name="t")
    by_layer: dict[str, list] = {}
    for layer, detail in checks:
        by_layer.setdefault(layer, []).append(
            CheckResult(layer, CheckStatus.FAIL, detail))
    for layer, cs in by_layer.items():
        r.add_layer(layer, cs)
    from validators.base import CheckStatus as CS
    r.pipeline_steps = [
        PipelineStepResult(step=n, status=CS.PASS if s == "pass" else CS.FAIL) for n, s in (steps or [])
    ]
    return r


class TestClassify:
    def test_design_contract(self):
        assert scoring._classify_check("design", "business_key 不符: x") == "design_contract"
        assert scoring._classify_check("design", "规则集不符: 多 ['R0002']") == "design_contract"
        assert scoring._classify_check("design", "load_mode 契约不符: x") == "design_contract"

    def test_design_default(self):
        assert scoring._classify_check("design", "join_key 非唯一但缺 strategy") == "design_default"

    def test_self_consistency_paths(self):
        assert scoring._classify_check("artifacts", "DDL列≠ts列[t]: DDL缺列 ['amt']") == "self_consistency"
        assert scoring._classify_check("artifacts", "DDL类型≠ts类型[t]: x") == "self_consistency"
        assert scoring._classify_check("code", "R0001: 字段覆盖契约缺字段: ['amt']") == "self_consistency"

    def test_artifact_default(self):
        assert scoring._classify_check("artifacts", "缺文件 (2): xxx") == "artifact"

    def test_pipeline(self):
        assert scoring._classify_check("pipeline", "preprocess") == "pipeline_stage"

    def test_golden_diff_map(self):
        assert scoring.classify_golden_diff("business_key") == "design_contract"
        assert scoring.classify_golden_diff("R0001:字段口径(total)") == "field_caliber"
        assert scoring.classify_golden_diff("DDL(列/类型)") == "self_consistency"
        assert scoring.classify_golden_diff("表结构(类型/分布键/build_mode)") == "structure_std"


class TestScoreResult:
    def test_all_pass_100(self, tmp_path):
        r = _mk_result([], [("preprocess", "pass"), ("designer", "pass")])
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["total"] == 100 and not s["deductions"]

    def test_deduction_math(self, tmp_path):
        r = _mk_result([
            ("design", "business_key 不符: x"),        # -20
            ("artifacts", "DDL列≠ts列[t]: DDL缺列"),   # -15
        ], [("coder(R0001)", "fail")])                 # -10
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["total"] == 100 - 20 - 15 - 10
        cats = [c for c, _, _ in s["deductions"]]
        assert sorted(cats) == sorted(["design_contract", "self_consistency", "pipeline_stage"])

    def test_floor_zero(self, tmp_path):
        r = _mk_result([("design", "business_key 不符")] * 10)
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["total"] == 0

    def test_golden_diffs_deduct(self, tmp_path):
        r = _mk_result([])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["business_key", "R0001:字段口径(total)"])
        assert s["has_golden"] is True
        assert s["total"] == 100 - 20 - 10

    def test_weights_override(self, tmp_path):
        r = _mk_result([("design", "business_key 不符: x")])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 weights_override={"design_contract": 50})
        assert s["total"] == 50


class TestRenderScore:
    def test_render_full_marks(self):
        out = scoring.render_score({"total": 100, "deductions": [], "has_golden": True}, prev_total=85)
        assert "100/100" in out and "85" in out and "零扣分" in out

    def test_render_deductions(self):
        out = scoring.render_score({
            "total": 70,
            "deductions": [("design_contract", 20, "business_key 不符: x"),
                           ("self_consistency", 15, "DDL列≠ts列")],
            "has_golden": True,
        })
        assert "70/100" in out
        assert "-20" in out and "design_contract" in out
        assert "-15" in out and "self_consistency" in out
