"""assemble_ddl_opt 测试：ALTER 变更单 + 全量 DDL + 差异审计（docs/specs/opt/05 §七）。"""
import json
from pathlib import Path

import pytest

from assemble_ts_baseline import build_ts_baseline
from assemble_ts_opt import apply_decisions
from assemble_ddl_opt import build_alter_ddl, declared_additions_by_table, audit_full_ddl, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def pair():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    b, _ = build_ts_baseline(demo)
    dec = {"change_type": "add_field", "backfill": "pending", "fields": [{
        "field": "channel_name", "target_table": "dwb_trade_order_d",
        "placed_rules": ["R0002"], "intermediate_tables": ["tmp_trade_order"],
        "field_type": "VARCHAR(64)", "field_comment": "渠道名称",
        "design_logic": "x", "transform_type": "direct", "source": {},
        "new_joins": []}]}
    # 中间表也要落位该字段（否则 fence 漏改）——decisions 上下两处都放
    dec["fields"][0]["placed_rules"] = ["R0001", "R0002"]
    return b, apply_decisions(b, dec)


class TestAlterDdl:
    def test_declared_additions_cover_intermediate(self, pair):
        b, v2 = pair
        adds = declared_additions_by_table(v2)
        assert set(adds) == {"dwb_trade_order_d", "tmp_trade_order"}
        assert adds["dwb_trade_order_d"][0]["field_type"] == "VARCHAR(64)"

    def test_build_alter_syntax(self):
        sql = build_alter_ddl("dws", "t1", [{"field": "c1", "field_type": "VARCHAR(64)",
                                             "field_comment": "渠道"}])
        assert "ALTER TABLE dws.t1 ADD COLUMN c1 VARCHAR(64);" in sql
        assert "COMMENT ON COLUMN dws.t1.c1 IS '渠道';" in sql

    def test_main_end_to_end(self, pair, tmp_path):
        b, v2 = pair
        bp = tmp_path / "b.json"; vp = tmp_path / "v2.json"
        bp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        vp.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        rc = main(["--ts-vaseline", str(bp)] if False else
                  ["--ts-v2", str(vp), "--ts-baseline", str(bp), "--outdir", str(tmp_path)])
        assert rc == 0
        assert (tmp_path / "ddl/alter_table_dwb_trade_order_d.sql").exists()
        assert (tmp_path / "ddl/alter_table_tmp_trade_order.sql").exists()
        assert (tmp_path / "ddl_full/create_table_dwb_trade_order_d.sql").exists()


class TestAudit:
    def test_clean_pass(self, pair):
        b, v2 = pair
        assert audit_full_ddl(b, v2) == []

    def test_smuggled_column_detected(self, pair):
        b, v2 = pair
        v2["tables"]["dwb_trade_order_d"]["fields"].append(
            {"target_field": "smuggler", "field_type": "INT", "field_comment": ""})
        problems = audit_full_ddl(b, v2)
        assert any("smuggler" in p for p in problems)

    def test_removed_column_detected(self, pair):
        b, v2 = pair
        v2["tables"]["dwb_trade_order_d"]["fields"] = [
            f for f in v2["tables"]["dwb_trade_order_d"]["fields"]
            if f["target_field"] != "cust_id"]
        problems = audit_full_ddl(b, v2)
        assert any("cust_id" in p and "不许删列" in p for p in problems)
