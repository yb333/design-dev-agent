"""slice_ts 优化模式切片测试（docs/specs/opt/05 §一）。

验证：opt 切片带 baseline SQL 原文 + 落位声明 + 硬约束；常规切片路径零变化。
"""
import json
from pathlib import Path

import pytest

from slice_ts import slice_rule, slice_rule_opt
from assemble_ts_baseline import build_ts_baseline
from assemble_ts_opt import apply_decisions
from fence_check import check

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"
B_R2 = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount "
        "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")


def dec_new_join():
    return {"change_type": "add_field", "backfill": "pending", "fields": [{
        "field": "channel_name", "target_table": "dwb_trade_order_d",
        "placed_rules": ["R0002"], "intermediate_tables": [],
        "field_type": "VARCHAR(64)", "field_comment": "渠道名称",
        "design_logic": "按订单关联渠道维表取渠道名称", "transform_type": "direct",
        "source": {"table": "dws.dim_channel", "alias": "c", "field": "channel_name"},
        "new_joins": [{
            "rule": "R0002", "schema": "dws", "table": "dim_channel", "alias": "c",
            "join_type": "LEFT", "on": "t.order_id = c.order_id",
            "join_safety": {"join_key_unique": True, "strategy": "直接关联",
                            "join_filter": "", "reason": "维表主键关联不发散"},
        }]}]}


@pytest.fixture(scope="module")
def v2():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    baseline, _ = build_ts_baseline(demo)
    return baseline, apply_decisions(baseline, dec_new_join())


class TestSliceOpt:
    def test_opt_slice_contents(self, v2):
        _, v2_ts = v2
        sliced = slice_rule_opt(v2_ts, "R0002", baseline_sql=B_R2)
        opt = sliced["opt"]
        assert opt["mode"] == "optimization" and opt["change_type"] == "add_field"
        assert opt["baseline_sql"] == B_R2, "baseline SQL 逐字原文"
        assert opt["declared_new_fields"][0]["field"] == "channel_name"
        assert opt["declared_new_joins"][0]["alias"] == "c"
        assert len(opt["hard_constraints"]) == 4
        # 常规切片信息也在（coder 要的字段/关联上下文）
        assert "channel_name" in json.dumps(sliced, ensure_ascii=False)

    def test_opt_slice_carries_buckets(self, v2):
        """opt 切片同样直出 fields 三桶（normalize 兜底旧 baseline）。"""
        _, v2_ts = v2
        sliced = slice_rule_opt(v2_ts, "R0002", baseline_sql=B_R2)
        assert set(sliced["fields"].keys()) == {"processed", "assign", "direct"}
        assert "opt" in sliced and "baseline_sql" in sliced["opt"]

    def test_unplaced_rule_gets_empty_decl(self, v2):
        baseline, v2_ts = v2
        sliced = slice_rule_opt(v2_ts, "R0001", baseline_sql="SELECT 1")
        assert sliced["opt"]["declared_new_fields"] == []
        assert sliced["opt"]["declared_new_joins"] == []

    def test_regular_slice_unchanged(self, v2):
        """加法式验证：不带 --baseline-sql 的常规切片行为不变（无 opt 键）。"""
        baseline, v2_ts = v2
        sliced = slice_rule(v2_ts, "R0002")
        assert "opt" not in sliced
