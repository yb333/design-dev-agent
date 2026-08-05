"""评测 v2 的 baseline 存档对比 + seed 测试。"""

import json
import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import baseline
from baseline import (
    BaselineSnapshot,
    CheckRecord,
    diff_against_baseline,
    find_latest_baseline,
    save_snapshot,
    snapshot_from_result,
)
from engine import EvalResult, PipelineStepResult
from validators.base import CheckResult, CheckStatus


def _eval_result(case="test", fails=None):
    """构造一个 EvalResult，fails 是 (layer, detail) 列表标 FAIL。"""
    fails = fails or []
    r = EvalResult(case_name=case)
    r.add_layer("artifacts", [
        CheckResult("artifacts", CheckStatus.FAIL if ("artifacts", "ts.json") in fails else CheckStatus.PASS, "ts.json 顶层键齐全"),
        CheckResult("artifacts", CheckStatus.FAIL if ("artifacts", "audit") in fails else CheckStatus.PASS, "audit_fields 正确"),
    ])
    return r


class TestBaselineSaveLoad:
    def test_save_and_find_latest(self, tmp_path, monkeypatch):
        """存档后能找到最新的。"""
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        snap = BaselineSnapshot(
            case_name="t", timestamp="2026-08-05T10:00:00", git_sha="abc",
            layer_stats={}, checks=[CheckRecord("artifacts", "ts.json", "pass", "ok")],
        )
        save_snapshot(snap)
        # 再存一份更晚的
        snap.timestamp = "2026-08-05T11:00:00"
        save_snapshot(snap)

        latest = find_latest_baseline("t")
        assert latest is not None
        assert latest.timestamp == "2026-08-05T11:00:00"

    def test_find_none_when_no_baseline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        assert find_latest_baseline("nope") is None


class TestBaselineDiff:
    def test_no_baseline_shows_none(self):
        r = _eval_result()
        d = diff_against_baseline(r, None)
        assert d.has_baseline is False

    def test_regression_detected(self):
        """上轮 pass，这轮 fail → 回退。"""
        baseline_snap = BaselineSnapshot(
            case_name="t", timestamp="t1", git_sha="x",
            layer_stats={},
            checks=[CheckRecord("artifacts", "ts.json", "pass", "ts.json 顶层键齐全")],
        )
        r = _eval_result(fails=[("artifacts", "ts.json")])  # 这轮 fail
        d = diff_against_baseline(r, baseline_snap)
        assert len(d.regressions) == 1
        assert "ts.json" in d.regressions[0]

    def test_fix_detected(self):
        """上轮 fail，这轮 pass → 修复。"""
        baseline_snap = BaselineSnapshot(
            case_name="t", timestamp="t1", git_sha="x",
            layer_stats={},
            checks=[CheckRecord("artifacts", "ts.json", "fail", "ts.json 顶层键齐全")],
        )
        r = _eval_result()  # 这轮全 pass
        d = diff_against_baseline(r, baseline_snap)
        assert len(d.fixes) == 1

    def test_new_failure_detected(self):
        """baseline 没有这条，这轮 fail → 新问题。"""
        baseline_snap = BaselineSnapshot(
            case_name="t", timestamp="t1", git_sha="x", layer_stats={}, checks=[],
        )
        r = _eval_result(fails=[("artifacts", "ts.json")])
        d = diff_against_baseline(r, baseline_snap)
        assert len(d.new_failures) == 1

    def test_no_change_when_identical(self):
        """完全一致 → 无变化。"""
        baseline_snap = BaselineSnapshot(
            case_name="t", timestamp="t1", git_sha="x",
            layer_stats={},
            checks=[CheckRecord("artifacts", "ts.json", "pass", "ts.json 顶层键齐全")],
        )
        r = _eval_result()
        d = diff_against_baseline(r, baseline_snap)
        assert d.regressions == []
        assert d.fixes == []
        assert d.new_failures == []


class TestCheckKey:
    """断言标识稳定性测试（保证跨轮对比能匹配同一条断言）。"""

    def test_key_stable_across_detail_change(self):
        """detail 的具体值变了，key 应稳定（用于对比）。"""
        from baseline import _check_key

        k1 = _check_key("design", "business_key 匹配: ['a','b']")
        k2 = _check_key("design", "business_key 不符: ['a']")
        # 首个关键词都是 business_key
        assert k1 == k2 == "business_key"

    def test_code_layer_key_includes_rule(self):
        """code 层的 key 应含 rule_code（区分不同规则的同类断言）。"""
        from baseline import _check_key

        k = _check_key("code", "R0001: GROUP BY 缺列: ['x']")
        assert k == "R0001:GROUP"
