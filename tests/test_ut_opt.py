"""ut_opt 测试：MINUS 构造 + 冻结列推导 + 假 executor 的对比判定（docs/specs/opt/06）。

不连库：输出对比判定逻辑用 fake executor（对齐 conftest 约定）；DB 路径（main）不测。
"""
import json
from pathlib import Path

import pytest

from ut_opt import build_compare_sql, _frozen_columns, run_output_compare, build_insert_plan

B_R2 = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount "
        "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")
N_R2 = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, c.channel_name "
        "FROM dws.tmp_trade_order t LEFT JOIN dws.dim_channel c ON t.order_id = c.order_id "
        "GROUP BY t.order_id, t.cust_id")

DECL = {"rule": "R0002", "fields": ["channel_name"],
        "new_joins": [{"rule": "R0002", "table": "dim_channel", "alias": "c",
                       "on": "t.order_id = c.order_id"}]}


class FakeExecutor:
    """count 查询按预设字典返回；样例查询返回空。"""

    def __init__(self, counts: dict):
        self.counts = counts
        self.queries = []

    def execute(self, sql):
        # EXPLAIN ANALYZE 预检：成功、空计划文本（真跑通/两门槛由 explain_check 单测覆盖）
        class _R:
            success, rows, error = True, [{"plan": "id | Operation | A-rows", "plan2": " 1 | Seq Scan | 10"}], None
        return _R()

    def fetch_all(self, sql):
        self.queries.append(sql)
        # 行数对账（cnt_o=老 / cnt_n=新，裸 COUNT 不含 MINUS）
        if "cnt_o" in sql and "COUNT" in sql:
            return [{"N": self.counts.get("old_rows", 10)}]
        if "cnt_n" in sql and "COUNT" in sql:
            return [{"N": self.counts.get("new_rows", 10)}]
        for key, n in self.counts.items():
            if key in sql and "COUNT" in sql:
                return [{"N": n}]
        return []


class TestBuildCompareSql:
    def test_minus_pair_shape(self, tmp_path):
        m1, m2 = build_compare_sql(B_R2, N_R2, ["order_id", "cust_id", "total_amount"],
                                   ["channel_name"])
        assert m1.startswith("SELECT") and "MINUS" in m1
        # 老侧子查询不改写本体
        assert "SUM(t.amount) AS total_amount" in m1
        # 新→老方向包含新列（差异可见供人审）
        assert "channel_name" in m2
        # 冻结列双向都裁剪投影
        assert '"order_id"' in m1 and '"order_id"' in m2


class TestFrozenColumns:
    def test_declared_excluded(self, tmp_path):
        ts = {"rules": {"R0002": {"field_targets": ["order_id", "cust_id",
                                                    "total_amount", "channel_name"]}},
              "change": {"fields": [{"field": "channel_name", "placed_rules": ["R0002"]}]}}
        frozen = _frozen_columns(ts, ts["change"])
        assert frozen["R0002"] == ["order_id", "cust_id", "total_amount"]


class TestCompareVerdict:
    def _setup(self, tmp_path, new_sql):
        etl = tmp_path / "etl"; etl.mkdir(exist_ok=True)
        base = tmp_path / "etl_baseline"; base.mkdir(exist_ok=True)
        (etl / "R0002.sql").write_text(new_sql, encoding="utf-8")
        (base / "R0002.sql").write_text(B_R2, encoding="utf-8")
        return etl, base

    def _ts(self):
        return {"rules": {"R0002": {"target_table": "dwb_trade_order_d",
                                    "field_targets": ["order_id", "cust_id",
                                                      "total_amount", "channel_name"]}},
                "change": {"change_type": "add_field", "fields": [
                    {"field": "channel_name", "target_table": "dwb_trade_order_d",
                     "placed_rules": ["R0002"],
                     "new_joins": [{"rule": "R0002", "table": "dim_channel", "alias": "c",
                                    "on": "t.order_id = c.order_id"}]}]}}

    def test_zero_diff_pass(self, tmp_path):
        etl, base = self._setup(tmp_path, N_R2)
        ex = FakeExecutor({"MINUS": 0})
        res = run_output_compare(ex, self._ts(), etl, base, {}, tmp_path)
        assert res[0]["status"] == "PASS"
        assert "零差异" in res[0]["detail"]

    def test_frozen_regression_fail(self, tmp_path):
        etl, base = self._setup(tmp_path, N_R2)
        # 老→新方向有差集（第一个 MINUS）→ FAIL；新→老方向（第二个）为 0
        ex = FakeExecutor({})
        ex.fetch_all = lambda sql: ([{"N": 3}] if "fence_old MINUS" in sql or
                                    ("MINUS" in sql and "COUNT" in sql
                                     and sql.index("MINUS") < sql.index("fence_new")
                                     and "cnt_" not in sql) else
                                    ([{"N": 0}] if "COUNT" in sql else []))
        res = run_output_compare(ex, self._ts(), etl, base, {}, tmp_path)
        assert res[0]["status"] == "FAIL" and "回归失败" in res[0]["detail"]

    def test_sql_fence_gate_inside_compare(self, tmp_path):
        """SQL 围栏不过（等价改写 WHERE）→ 对比前拦下，不进 MINUS。"""
        bad = N_R2 + " WHERE 1=1"  # 语法上叠加 where 会被围栏拦
        etl, base = self._setup(tmp_path, bad)
        ex = FakeExecutor({})
        res = run_output_compare(ex, self._ts(), etl, base, {}, tmp_path)
        assert res[0]["status"] == "FENCE_FAIL"


class TestInsertPlan:
    """表名两种形态（json 路径短名 / 档案路径 new-pipe 新版带 schema）产出同一 INSERT 计划。"""

    def _ts(self, prefixed: bool):
        tt = "dws.dwb_trade_order_d" if prefixed else "dwb_trade_order_d"
        return {"rules": {"R0002": {"target_table": tt}},
                "tables": {"dwb_trade_order_d": {"fields": [{"target_field": "order_id"}]}}}

    def test_short_and_prefixed_agree(self, tmp_path):
        short = build_insert_plan(self._ts(False), "dws")
        prefixed = build_insert_plan(self._ts(True), "dws")
        assert short == prefixed == [("R0002", "dws.dwb_trade_order_d", ["order_id"])]


class TestNewColumnNulls:
    def test_all_null_flags_join_miss(self, tmp_path):
        """全 NULL → 疑似新 JOIN 关联不上信号（LEFT JOIN 常态形态）。"""
        from ut_opt import check_new_column_nulls

        class NullEx:
            def fetch_all(self, sql):
                assert "null_channel_name" in sql
                return [{"total": 100, "null_channel_name": 100}]

        ts = {"change": {"fields": [
            {"field": "channel_name", "target_table": "dwb_x_d"}]}}
        out = check_new_column_nulls(NullEx(), ts, "dws")
        assert out[0]["nulls"] == 100 and out[0]["total"] == 100
        assert "关联不上" in out[0]["note"]

    def test_partial_null_and_clean(self, tmp_path):
        from ut_opt import check_new_column_nulls

        class NullEx:
            def __init__(self, ret):
                self.ret = ret
            def fetch_all(self, sql):
                return [self.ret]

        ts = {"change": {"fields": [{"field": "c1", "target_table": "t1"}]}}
        # 半数 NULL：过半提示
        out = check_new_column_nulls(NullEx({"total": 10, "null_c1": 6}), ts, "dws")
        assert "过半" in out[0]["note"]
        # 干净：无提示
        out2 = check_new_column_nulls(NullEx({"total": 10, "null_c1": 0}), ts, "dws")
        assert out2[0]["note"] == ""


class TestRowCountReconciliation:
    """行数对账（多重集守护）：MINUS 是集合语义看不见重复数——新 JOIN 发散的行级硬信号。"""

    def _setup(self, tmp_path):
        etl = tmp_path / "etl"; etl.mkdir()
        base = tmp_path / "base"; base.mkdir()
        (etl / "R0002.sql").write_text("SELECT 1 AS a, 2 AS b", encoding="utf-8")
        (base / "R0002.sql").write_text("SELECT 1 AS a", encoding="utf-8")
        return etl, base

    def _ts(self):
        return {"change": {"fields": [
            {"field": "b", "target_table": "t1", "placed_rules": ["R0002"],
             "intermediate_tables": [], "new_joins": []}]},
            "rules": {"R0002": {"field_targets": ["a", "b"],
                                "source_tables": [{"schema": "ods", "table": "o", "alias": "a"}]}},
            "meta": {"target": {"f_table": {"schema": "dws", "table": "t1"}}}}

    def test_row_drift_fails_with_diagnose_hint(self, tmp_path):
        etl, base = self._setup(tmp_path)
        ex = FakeExecutor({"old_rows": 100, "new_rows": 340})   # 发散 3.4 倍
        res = run_output_compare(ex, self._ts(), etl, base, {}, tmp_path)
        assert res[0]["status"] == "FAIL"
        assert "行数漂移" in res[0]["detail"] and "diagnose_fanout_opt" in res[0]["detail"]

    def test_equal_rows_proceeds_to_minus(self, tmp_path):
        etl, base = self._setup(tmp_path)
        ex = FakeExecutor({"old_rows": 100, "new_rows": 100, "MINUS": 0})
        res = run_output_compare(ex, self._ts(), etl, base, {}, tmp_path)
        assert res[0]["status"] == "PASS"


class TestFenceStalenessGate:
    """围栏时效闸门：SQL 晚于围栏结果 = 过期，UT 拒跑（回路铁律机器化）。"""

    def _run_main(self, tmp_path, fence_exists=True, stale=False):
        import os, time
        etl = tmp_path / "etl"; etl.mkdir(exist_ok=True)
        (etl / "R0002.sql").write_text("SELECT 1", encoding="utf-8")
        internal = tmp_path / "_internal"
        if fence_exists:
            internal.mkdir(exist_ok=True)
            fr = internal / "sql_fence_result.json"
            fr.write_text('{"passed": true}', encoding="utf-8")
            if stale:
                past = time.time() - 100
                os.utime(etl / "R0002.sql", (time.time() + 50, time.time() + 50))
        ts_path = tmp_path / "ts_v2.json"
        ts_path.write_text(json.dumps(self._ts()), encoding="utf-8")
        from ut_opt import main
        return main(["--ts", str(ts_path), "--etl-dir", str(etl), "--baseline-dir", str(tmp_path),
                     "--ddl-dir", str(tmp_path), "--report", str(tmp_path / "r.md")])

    def _ts(self):
        return {"change": {"fields": [{"field": "b", "target_table": "t1"}]},
                "meta": {"target": {"f_table": {"schema": "dws", "table": "t1"}}}}

    def test_missing_fence_result_exit_2(self, tmp_path):
        assert self._run_main(tmp_path, fence_exists=False) == 2

    def test_stale_fence_exit_2(self, tmp_path):
        assert self._run_main(tmp_path, fence_exists=True, stale=True) == 2
