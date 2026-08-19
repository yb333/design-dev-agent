"""ut_opt 测试：MINUS 构造 + 冻结列推导 + 假 executor 的对比判定（docs/specs/opt/06）。

不连库：输出对比判定逻辑用 fake executor（对齐 conftest 约定）；DB 路径（main）不测。
"""
import json
from pathlib import Path

import pytest

from ut_opt import build_compare_sql, _frozen_columns, run_output_compare

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

    def fetch_all(self, sql):
        self.queries.append(sql)
        for key, n in self.counts.items():
            if key in sql and "COUNT" in sql:
                return [{"N": n}]
        return []


class TestBuildCompareSql:
    def test_minus_pair_shape(self):
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
    def test_declared_excluded(self):
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
        res = run_output_compare(ex, self._ts(), etl, base, {})
        assert res[0]["status"] == "PASS"
        assert "零差异" in res[0]["detail"]

    def test_frozen_regression_fail(self, tmp_path):
        etl, base = self._setup(tmp_path, N_R2)
        # 老→新方向有差集（第一个 MINUS）→ FAIL；新→老方向（第二个）为 0
        ex = FakeExecutor({})
        ex.fetch_all = lambda sql: ([{"N": 3}] if "fence_old MINUS" in sql or
                                    (sql.index("MINUS") < sql.index("fence_new")
                                     and "COUNT" in sql) else
                                    ([{"N": 0}] if "COUNT" in sql else []))
        res = run_output_compare(ex, self._ts(), etl, base, {})
        assert res[0]["status"] == "FAIL" and "回归失败" in res[0]["detail"]

    def test_sql_fence_gate_inside_compare(self, tmp_path):
        """SQL 围栏不过（等价改写 WHERE）→ 对比前拦下，不进 MINUS。"""
        bad = N_R2 + " WHERE 1=1"  # 语法上叠加 where 会被围栏拦
        etl, base = self._setup(tmp_path, bad)
        ex = FakeExecutor({})
        res = run_output_compare(ex, self._ts(), etl, base, {})
        assert res[0]["status"] == "FENCE_FAIL"
