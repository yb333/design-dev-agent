"""ut_precheck._explain_check 测试：执行计划两门槛（fake executor，不连库）。

门槛定调（2026-09-02 用户拍板，只做这两个）：
- STREAM 算子出现个数 ≤ 50（Gather/Redistribute/Broadcast——过多→大量线程消耗性能降）；
- 不下推（计划含 Row Adapter 等 CN 侧标志——内网实测后可调模式常量）。
过程可视：计划原文全量落盘 _internal/diagnose/plan_{rule}.txt（好坏都留，人可回溯）。
提示级不阻断。纯 EXPLAIN（零执行成本，形状信号无需 ANALYZE）。
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "new-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from ut_precheck import _explain_check, _STREAM_PATTERN  # noqa: E402


class _R:
    def __init__(self, rows=None, success=True, error=""):
        self.success, self.rows, self.error = success, rows or [], error


class _Ex:
    def __init__(self, plan_lines=None, error=""):
        self.plan_lines = plan_lines or []
        self.error = error
        self.captured: list[str] = []

    def execute(self, sql):
        self.captured.append(sql)
        if self.error:
            return _R(success=False, error=self.error)
        return _R([{"QUERY PLAN": ln} for ln in self.plan_lines])


def _plan_with_streams(n: int, extra: str = "") -> list[str]:
    return (["Streaming (type: GATHER)"] * n
            + ["Streaming (type: REDISTRIBUTE)"]
            + ["Stream[name:S1, type: BROADCAST]"]      # openGauss 风格格式也认
            + ([extra] if extra else []))


class TestStreamThreshold:
    def test_under_limit_passes_and_plan_saved(self, tmp_path):
        ex = _Ex(_plan_with_streams(3))
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, plan_file = _explain_check(ex, "SELECT 1", "R0001", tmp_path / "ts.json")
        assert issues == []
        assert plan_file and Path(plan_file).exists()
        assert "SELECT 1" in Path(plan_file).read_text(encoding="utf-8")   # SQL 原文同落盘（可回溯）
        assert ex.captured[0].startswith("EXPLAIN SELECT 1")

    def test_over_limit_flags(self, tmp_path):
        ex = _Ex(_plan_with_streams(48))                  # 48+1+1 = 50 个 → 不超
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, _ = _explain_check(ex, "SELECT 1", "R0001", tmp_path / "ts.json")
        assert issues == []
        ex2 = _Ex(_plan_with_streams(49))                 # 51 个 → 超
        issues2, _ = _explain_check(ex2, "SELECT 1", "R0001", tmp_path / "ts.json")
        assert any("STREAM 算子 51 个 > 50" in i for i in issues2)

    def test_pattern_matches_both_formats(self):
        text = ("Streaming (type: GATHER)\n"
                "Stream[name:S2, type: REDISTRIBUTE]\n"
                "->  Streaming(type: BROADCAST)")
        assert len(_STREAM_PATTERN.findall(text)) == 3


class TestNoPushdown:
    def test_row_adapter_flags(self, tmp_path):
        ex = _Ex(["Row Adapter", "Streaming (type: GATHER)"])
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, _ = _explain_check(ex, "SELECT 1", "R0001", tmp_path / "ts.json")
        assert any("不下推" in i and "Row Adapter" in i for i in issues)

    def test_explain_failure_disclosed_not_blocking(self, tmp_path):
        ex = _Ex(error="permission denied")
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, plan_file = _explain_check(ex, "SELECT 1", "R0001", tmp_path / "ts.json")
        assert any("EXPLAIN 失败（计划门槛跳过）" in i for i in issues)
        assert plan_file == ""                             # 失败不落盘
