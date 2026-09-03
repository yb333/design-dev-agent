"""ut_precheck 计划分析测试（fake，不连库）。

2026-09-03 定调（用户）：EXPLAIN ANALYZE 真实执行一次（不带采样）**替代**采样 SELECT——
一次执行三份收获：真跑通验证 + 计划两门槛 + 顶层实际行数（多格式解析，失败=宁缺勿错
跳过 0 行告警不猜）。门槛：①不下推=Data Node Scan（官方判据；Row Adapter 非判据已纠正）
②STREAM 算子出现个数 ≤50。计划原文（含 actual 值）全量落盘可回溯（过程可视）。
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "new-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from ut_precheck import _analyze_plan, _parse_actual_rows, _STREAM_PATTERN  # noqa: E402


def _plan_with_streams(n: int, extra: str = "") -> str:
    return ("\n".join(["Streaming (type: GATHER)"] * n
                      + ["Streaming (type: REDISTRIBUTE)"]
                      + ["Stream[name:S1, type: BROADCAST]"]
                      + ([extra] if extra else [])))


class TestActualRowsParse:
    def test_pg_text_style(self):
        plan = "Streaming (type: GATHER) (cost=.. rows=100)\n   (actual time=1.2..3.4 rows=87 loops=1)"
        assert _parse_actual_rows(plan) == 87

    def test_rows_loops_variant(self):
        assert _parse_actual_rows("(... rows=42 loops=1)") == 42

    def test_dws_table_style_first_row(self):
        plan = " id | operation | A-time | A-rows\n 1 | -> Streaming (type: GATHER) | 3.2 | 55"
        assert _parse_actual_rows(plan) == 55

    def test_unrecognized_returns_none(self):
        assert _parse_actual_rows("啥都没有") is None       # 宁缺勿错：不猜


class TestStreamThreshold:
    def test_under_limit_passes_and_plan_saved(self, tmp_path):
        plan = _plan_with_streams(3)
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, plan_file = _analyze_plan(plan, "R0001", tmp_path / "ts.json")
        assert issues == []
        assert plan_file and Path(plan_file).exists()
        assert "EXPLAIN ANALYZE" in Path(plan_file).read_text(encoding="utf-8")  # 落盘含标记

    def test_over_limit_flags(self, tmp_path):
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, _ = _analyze_plan(_plan_with_streams(48), "R0001", tmp_path / "ts.json")   # 50 个 → 不超
        assert issues == []
        issues2, _ = _analyze_plan(_plan_with_streams(49), "R0001", tmp_path / "ts.json")  # 51 → 超
        assert any("STREAM 算子 51 个 > 50" in i for i in issues2)

    def test_pattern_matches_both_formats_and_any_type(self):
        text = ("Streaming (type: GATHER)\n"
                "Stream[name:S2, type: REDISTRIBUTE]\n"
                "->  Streaming(type: BROADCAST)\n"
                "Streaming (type: PART REDISTRIBUTE)\n"
                "Streaming (type: PART LOCAL)")
        assert len(_STREAM_PATTERN.findall(text)) == 5


class TestNoPushdown:
    def test_data_node_scan_flags(self, tmp_path):
        plan = 'Data Node Scan on t1 "_REMOTE_TABLE_QUERY_"\nStreaming (type: GATHER)'
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, _ = _analyze_plan(plan, "R0001", tmp_path / "ts.json")
        assert any("不下推" in i and "Data Node Scan" in i and "_REMOTE_TABLE_QUERY_" in i for i in issues)

    def test_row_adapter_alone_not_flagged(self, tmp_path):
        """Row Adapter 只是行列转换算子不算（首版误用已纠正）。"""
        (tmp_path / "ts.json").write_text("{}", encoding="utf-8")
        issues, _ = _analyze_plan("Row Adapter\nStreaming (type: GATHER)", "R0001", tmp_path / "ts.json")
        assert not any("不下推" in i for i in issues)
