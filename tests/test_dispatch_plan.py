"""dispatch_plan 测试——执行计划的 dq 行（2026-09-22：DQ 内容拆分后在计划中隐形，
按清单发起的 pipe 会漏 4c；meta.dq_required 装配携带，false 显式跳过）。"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "new-pipe" / "scripts"))

from dispatch_plan import build_dispatch_plan  # noqa: E402


def _ts(dq_required=None, dq_rules=None):
    ts = {"rules": {"R0001": {"exec_sequence": 1}}, "meta": {}, "tables": {}}
    if dq_required is not None:
        ts["meta"]["dq_required"] = dq_required
    if dq_rules is not None:
        ts["dq_rules"] = dq_rules
    return ts


class TestDqRow:
    def test_dq_required_true_with_count(self):
        plan = build_dispatch_plan(_ts(dq_required=3))
        assert plan["dq"] == {"required": True, "requirements": 3}
        assert "DQ 3 条" in plan["summary"] and "4c" in plan["summary"]

    def test_zero_explicit_skip(self):
        """required=false 显式跳过——计划里明示"跳过"比"没有"强（人扫一眼知道不是漏了）。"""
        plan = build_dispatch_plan(_ts(dq_required=0))
        assert plan["dq"] == {"required": False, "requirements": 0}
        assert "无 DQ 需求" in plan["summary"] and "4c 跳过" in plan["summary"]

    def test_legacy_ts_dq_rules_fallback(self):
        """旧档（DQ 拆分前）无 meta.dq_required 键——按 ts.dq_rules 兜底。"""
        plan = build_dispatch_plan(_ts(dq_rules=[{"rule_name": "x"}]))
        assert plan["dq"]["required"] is True and plan["dq"]["requirements"] == 1

    def test_legacy_ts_nothing_means_no_dq(self):
        """旧档无键无 dq_rules=无 DQ（显式 false）。"""
        plan = build_dispatch_plan(_ts())
        assert plan["dq"] == {"required": False, "requirements": 0}

    def test_basic_plan_shape_regression(self):
        plan = build_dispatch_plan(_ts(dq_required=0))
        assert plan["ddl"] is True and plan["etl_rules"] == ["R0001"] and plan["init_rules"] == []
