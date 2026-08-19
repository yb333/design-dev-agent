"""assemble_ts_opt 测试：ts_baseline + 增量 decisions → ts_v2（docs/specs/opt/04 §二）。

集成验证闭环：产出 ts_v2 必须过 fence_check（组装器与围栏是同一契约的两端）。
不连库；baseline 由 demo fixture 现场组装。
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

from assemble_ts_baseline import build_ts_baseline
from assemble_ts_opt import load_decisions, validate_decisions, apply_decisions, main
from fence_check import check

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def baseline():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    return ts


def dec_direct():
    return {
        "change_type": "add_field", "backfill": "pending",
        "fields": [{
            "field": "pay_channel", "target_table": "dwb_trade_order_d",
            "placed_rules": ["R0002"], "intermediate_tables": [],
            "field_type": "VARCHAR(64)", "field_comment": "支付渠道",
            "design_logic": "支付渠道编码直取", "transform_type": "direct",
            "source": {"table": "ods.ods_trade_order_di", "alias": "a", "field": "pay_channel"},
            "new_joins": [],
        }],
    }


def dec_new_join():
    d = dec_direct()
    d["fields"][0] = {
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
        }],
    }
    return d


def cr_for(*fields):
    return {"change_type": "add_field", "asset": "dws.dwb_trade_order_d",
            "fields": [{"field": f, "cn": f, "type": "VARCHAR(64)",
                        "source": {"table": "dim_channel", "alias": "c", "field": f},
                        "new_source_table": True} for f in fields],
            "backfill": "pending"}


class TestApplyAndFenceIntegration:
    def test_direct_passes_fence(self, baseline):
        v2 = apply_decisions(baseline, dec_direct())
        assert check(baseline, v2, cr_for("pay_channel")) == []

    def test_new_join_passes_fence(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        assert check(baseline, v2, cr_for("channel_name")) == []

    def test_baseline_not_mutated(self, baseline):
        snap = json.dumps(baseline, sort_keys=True)
        apply_decisions(baseline, dec_new_join())
        assert json.dumps(baseline, sort_keys=True) == snap, "组装不得污染 baseline"

    def test_change_section_shape(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        ch = v2["change"]
        assert ch["change_type"] == "add_field"
        f = ch["fields"][0]
        assert f["field"] == "channel_name" and f["placed_rules"] == ["R0002"]
        assert f["new_joins"][0]["table"] == "dim_channel"
        assert "join_safety" not in f["new_joins"][0], "change 段不带 safety 细节（落 ts 规则里）"

    def test_join_safety_landed_on_rule(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        js = v2["rules"]["R0002"]["join_safety"]
        assert any(x["table"] == "dim_channel" and x["join_key_unique"] for x in js)

    def test_intermediate_chain(self, baseline):
        d = dec_new_join()
        f = d["fields"][0]
        f["placed_rules"] = ["R0001", "R0002"]
        f["intermediate_tables"] = ["tmp_trade_order"]
        f["new_joins"][0]["rule"] = "R0001"
        v2 = apply_decisions(baseline, d)
        assert "channel_name" in {x["target_field"]
                                  for x in v2["tables"]["tmp_trade_order"]["fields"]}
        assert check(baseline, v2, cr_for("channel_name")) == []


class TestValidationFailLoud:
    def test_existing_field_rejected(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["field"] = "order_id"
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_safety_required(self, baseline, tmp_path):
        d = dec_new_join()
        d["fields"][0]["new_joins"][0].pop("join_safety")
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_on_unplaced_rule_rejected(self, baseline, tmp_path):
        d = dec_new_join()
        d["fields"][0]["new_joins"][0]["rule"] = "R0001"   # 不在 placed_rules
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_missing_required_key(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0].pop("design_logic")
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)


class TestMain:
    def test_main_end_to_end(self, baseline, tmp_path):
        d = dec_new_join()
        dp = tmp_path / "d.yaml"
        dp.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        bp = tmp_path / "ts_baseline.json"
        bp.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "ts_v2.json"
        assert main(["--ts-baseline", str(bp), "--decisions", str(dp),
                     "--output", str(out)]) == 0
        v2 = json.loads(out.read_text(encoding="utf-8"))
        assert v2["generated_by"] == "assemble_ts_opt"
        assert check(baseline, v2, cr_for("channel_name")) == [], \
            "main 产出的 ts_v2 必须过围栏（组装器与围栏同契约）"
