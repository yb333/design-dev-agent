"""两级评分测试：致命门 / 非致命扣分 / 根因去重 / passed。"""

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


def _mk_result(checks, steps=None, golden_fail=None):
    """checks: [(layer, detail)] 全 FAIL；golden_fail: golden 层 detail（或 None）。"""
    r = EvalResult(case_name="t")
    by_layer = {}
    for layer, detail in checks:
        by_layer.setdefault(layer, []).append(CheckResult(layer, CheckStatus.FAIL, detail))
    if golden_fail:
        by_layer.setdefault("golden", []).append(CheckResult("golden", CheckStatus.FAIL, golden_fail))
    for layer, cs in by_layer.items():
        r.add_layer(layer, cs)
    r.pipeline_steps = [
        PipelineStepResult(step=n, status=CheckStatus.PASS if s == "pass" else CheckStatus.FAIL)
        for n, s in (steps or [])
    ]
    return r


class TestFatalGate:
    def test_all_pass_100_and_passed(self, tmp_path):
        r = _mk_result([], [("preprocess", "pass"), ("designer", "pass")])
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["total"] == 100 and s["passed"] is True and not s["fatal"]

    def test_field_coverage_fatal(self, tmp_path):
        r = _mk_result([("code", "R0001: 字段覆盖契约缺字段: ['amt']")])
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["passed"] is False and "字段覆盖" in s["fatal"][0]
        assert s["total"] == 80

    def test_business_key_fatal(self, tmp_path):
        r = _mk_result([("design", "business_key 不符: x")])
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["passed"] is False and s["total"] == 80

    def test_type_input_fatal(self, tmp_path):
        r = _mk_result([("design", "类型不符输入要求: [('amt', 'int/decimal')]")])
        s = scoring.score_result(r, tmp_path, tmp_path)
        assert s["passed"] is False

    def test_caliber_logic_fatal_from_golden(self, tmp_path):
        r = _mk_result([])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["R0001:口径逻辑(total_amt)"])
        assert s["passed"] is False and s["total"] == 80


class TestNonFatal:
    def test_structure_drift_passes(self, tmp_path):
        """表结构漂移 + 精度差异：扣分但及格（交付安全）。"""
        r = _mk_result([])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["表结构(类型/分布键/build_mode)",
                                               "DDL(类型精度): t1.amt"])
        assert s["passed"] is True
        assert s["total"] == 100 - 5 - 2

    def test_const_drift_nonfatal(self, tmp_path):
        r = _mk_result([])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["R0001:口径常量(del_flag)"])
        assert s["passed"] is True and s["total"] == 98


class TestRootDedupe:
    def test_same_root_counted_once(self, tmp_path):
        """契约断言已扣 business_key，golden 同维度差异不再扣（根因去重）。"""
        r = _mk_result([("design", "business_key 不符: [a] ≠ [b]")])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["business_key"])
        assert s["total"] == 80  # 只扣一次
        assert s["passed"] is False

    def test_ddl_columns_dedupe(self, tmp_path):
        r = _mk_result([("artifacts", "DDL列≠ts列[t]: DDL缺列 ['amt']")])
        s = scoring.score_result(r, tmp_path, tmp_path,
                                 golden_diffs=["DDL(列): t.amt"])
        assert s["total"] == 80


class TestRender:
    def test_render_pass(self):
        out = scoring.render_score(
            {"total": 95, "deductions": [("structure_std", 5, "表结构漂移", False)],
             "fatal": [], "passed": True, "has_golden": True}, prev_total=85)
        assert "✔及格（交付安全）95/100" in out and "85" in out

    def test_render_fail_lists_fatal(self):
        out = scoring.render_score(
            {"total": 60, "deductions": [("fatal", 20, "字段覆盖契约缺字段", True),
                                         ("fatal", 20, "business_key 不符", True)],
             "fatal": ["字段覆盖契约缺字段", "business_key 不符"],
             "passed": False, "has_golden": True})
        assert "✘不及格 60/100" in out
        assert "字段覆盖" in out and "business_key" in out

    def test_render_no_golden_warns(self):
        out = scoring.render_score(
            {"total": 100, "deductions": [], "fatal": [], "passed": True, "has_golden": False})
        assert "无golden" in out


class TestDisciplineScoring:
    """纪律违规：FAIL 但不拦及格（-10 待人裁决）。"""

    def test_discipline_fail_not_fatal(self):
        r = _mk_result([("discipline", "agent 自建脚本 1 处（绕过流程，待人裁决）")])
        s = scoring.score_result(r, Path("/tmp"), Path("/tmp"))
        assert s["passed"] is True  # 不进致命门
        assert s["total"] == 90     # -10

    def test_discipline_pass_clean(self):
        r = _mk_result([])
        s = scoring.score_result(r, Path("/tmp"), Path("/tmp"))
        assert s["total"] == 100
