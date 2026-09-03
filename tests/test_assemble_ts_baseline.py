"""assemble_ts_baseline 测试：契约 → ts_baseline 基线包（docs/specs/opt/02）。

不连库；数据来自 tests/fixtures/opt 的两份契约 fixture（v1.0 demo + v1.1 增量合并）。
"""
import json
import copy
from pathlib import Path

import pytest

from assemble_ts_baseline import (
    build_ts_baseline, derive_topology, render_baseline_view,
    KIND_TO_LOAD_MODE, PENDING_KINDS,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def demo():
    return json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def merge_case():
    return json.loads((FIXTURES / "baseline_v1_case_merge_upsert.json").read_text(encoding="utf-8"))


class TestTopology:
    def test_demo_two_step_chain(self, demo):
        topo = derive_topology(demo["rules"])
        assert topo["_table_roles"]["dws.tmp_trade_order"] == "intermediate"
        assert topo["_table_roles"]["dws.dwb_trade_order_d"] == "target"
        # 方向：R0001 的表被 R0002 读 → R0001.produces_for 含 R0002；R0002.reads 含 tmp（全名）
        assert topo["R0001"]["produces_for"] == ["R0002"]
        assert topo["R0002"]["reads_tables"] == ["dws.tmp_trade_order"]
        assert topo["R0002"]["target_full"] == "dws.dwb_trade_order_d"


class TestDemoFullCase:
    def test_build_and_key_slots(self, demo):
        ts, gaps = build_ts_baseline(demo)
        assert ts["generated_by"] == "assemble_ts_baseline"
        assert ts["_baseline"]["contract_version"] == "1.1"
        assert ts["meta"]["target"]["f_table"]["table"] == "dwb_trade_order_d"
        # load_mode 映射：dm=1→truncate_table，dm=5→truncate_partition
        assert ts["rules"]["R0001"]["load_mode"] == "truncate_table"
        assert ts["rules"]["R0002"]["load_mode"] == "truncate_partition"
        assert ts["rules"]["R0001"]["target_role"] == "intermediate"
        assert ts["rules"]["R0002"]["target_role"] == "target"
        # 结构事实填充
        assert ts["rules"]["R0002"]["reads"] == ["dws.tmp_trade_order"]  # N12b 带 schema
        assert ts["rules"]["R0002"]["target_table"] == "dws.dwb_trade_order_d"
        assert "dwb_trade_order_d" in ts["tables"]  # tables 键仍短名
        assert ts["rules"]["R0001"]["source_tables"][0]["table"] == "ods_trade_order_di"
        assert ts["rules"]["R0001"]["joins"][0]["alias"] == "a"
        # 语义位留空（不伪造）
        assert ts["rules"]["R0001"]["step_type"] == ""
        assert ts["rules"]["R0001"]["join_safety"] == []
        assert ts["design"]["business_key"] == []
        # 字段：dwb 的三个字段带类型；field_targets 来自血缘
        dwb = ts["tables"]["dwb_trade_order_d"]
        assert {f["target_field"] for f in dwb["fields"]} == {"order_id", "cust_id", "total_amount"}
        assert ts["rules"]["R0002"]["field_targets"] == ["cust_id", "order_id", "total_amount"]
        # 血缘 enrich：total_amount 是 aggregate
        tamt = next(f for f in dwb["fields"] if f["target_field"] == "total_amount")
        assert tamt["transform_type"] == "aggregate"
        assert tamt["source_fields"][0]["table"] == "ods.ods_trade_order_di"
        # 中间表字段从血缘补骨架（DDL fields 缺类型也不丢字段名）
        assert {f["target_field"] for f in ts["tables"]["tmp_trade_order"]["fields"]} \
               == {"order_id", "cust_id", "amount"}
        # data_flow：依赖方向 + 调度分组
        assert ts["data_flow"]["dependencies"] == [
            {"from": "R0001", "to": "R0002", "type": "data_flow",
             "intermediate_table": "dws.tmp_trade_order"}]
        assert ts["data_flow"]["schedule_groups"] == [
            {"sequence": 1, "rules": ["R0001"]}, {"sequence": 2, "rules": ["R0002"]}]

    def test_semantic_gaps_recorded(self, demo):
        _, gaps = build_ts_baseline(demo)
        codes = {g["code"] for g in gaps}
        assert {"business_key", "join_safety", "step_type", "field_logics",
                "distribution_key", "init_section"} <= codes
        assert not any(g["code"] == "load_mode_pending" for g in gaps), \
            "demo 全量链路不应有写入类型待定"

    def test_dq_rules_mapped(self, demo):
        ts, _ = build_ts_baseline(demo)
        assert len(ts["dq_rules"]) == 2
        assert ts["dq_rules"][0]["check_type"] == "NULL"

    def test_view_contains_sections(self, demo):
        ts, gaps = build_ts_baseline(demo)
        view = render_baseline_view(demo, ts, gaps)
        for section in ("# baseline_view", "## 规则清单", "## 增量材料",
                        "## 字段血缘摘要", "## warnings", "## 语义空位"):
            assert section in view
        assert "R0002" in view and "tmp_trade_order" in view


class TestMergeCase:
    def test_dm6_rule(self, merge_case):
        ts, gaps = build_ts_baseline(merge_case)
        r2 = ts["rules"]["R0002"]
        assert r2["load_mode"] == "merge_into"
        assert r2["write_condition"] == "m.order_id = t.order_id"
        assert r2["target_role"] == "target"
        assert not any(g["code"] == "load_mode_pending" for g in gaps)

    def test_dm1_no_condition(self, merge_case):
        ts, _ = build_ts_baseline(merge_case)
        assert ts["rules"]["R0001"]["write_condition"] == ""


class TestPendingKind:
    def test_pending_kind_no_fake_mapping(self, demo):
        """词表外的 kind：load_mode 留空 + 待定记录，禁止硬映射（无假信息镜像）。"""
        bad = copy.deepcopy(demo)
        bad["rules"][0]["write_plan"] = {
            "kind": "exchange_partition", "condition_role": "exchange_table",
            "condition_expr": "P_202608", "condition_columns": [],
            "condition_source": "exchange_config"}
        ts, gaps = build_ts_baseline(bad)
        assert ts["rules"]["R0001"]["load_mode"] == ""
        pend = [g for g in gaps if g["code"] == "load_mode_pending"]
        assert len(pend) == 1 and pend[0]["target"] == "R0001"
        view = render_baseline_view(bad, ts, gaps)
        assert "写入类型待定" in view and "exchange_partition" in view

    def test_kind_map_covers_non_pending(self):
        """已映射 kind 与待定 kind 互斥且为词表全集校验。"""
        all_kinds = set(KIND_TO_LOAD_MODE) | PENDING_KINDS
        assert "merge_upsert" in KIND_TO_LOAD_MODE
        assert {"subpartition_truncate", "rpt_item", "exchange_partition", "unknown"} \
               <= PENDING_KINDS
        assert not (set(KIND_TO_LOAD_MODE) & PENDING_KINDS), "映射与待定不得重叠"


class TestV10NoWritePlan:
    def test_missing_write_plan_is_explicit_gap(self, merge_case):
        """v1.0 形态（无 write_plan）：load_mode 留空 + write_plan_missing 缺口，不回退本侧 dm 映射。"""
        v10 = copy.deepcopy(merge_case)
        v10["version"] = "1.0"
        for r in v10["rules"]:
            r.pop("write_plan", None)
        ts, gaps = build_ts_baseline(v10)
        assert ts["rules"]["R0002"]["load_mode"] == ""
        assert ts["rules"]["R0002"]["write_condition"] == ""
        miss = [g for g in gaps if g["code"] == "write_plan_missing"]
        assert len(miss) == 2, "两规则都应记缺口"


class TestVerbatimSql:
    def test_query_sql_verbatim_pass_through(self, demo, tmp_path):
        """main 落档的 etl 与契约 query_sql 逐字节一致（含紧凑写法）；
        档案件落 archive/、过程件落 internal/（目录定调 2026-08-31）。"""
        import assemble_ts_baseline as m
        archive, internal = tmp_path / "archive", tmp_path / "internal"
        src = tmp_path / "baseline_v1.json"
        src.write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
        rc = m.main(["--baseline", str(src), "--archive-dir", str(archive),
                     "--internal-dir", str(internal)])
        assert rc == 0
        sql1 = (archive / "etl" / "R0001.sql").read_text(encoding="utf-8")
        assert sql1 == demo["rules"][0]["query_sql"]
        assert (archive / "ts.json").exists()
        assert (internal / "exemptions.json").exists()
        assert (internal / "baseline_view.md").exists()

    def test_contract_violation_exit2(self, demo, tmp_path, capsys):
        import assemble_ts_baseline as m
        bad = copy.deepcopy(demo)
        bad["version"] = "9.9"
        src = tmp_path / "bad.json"
        src.write_text(json.dumps(bad), encoding="utf-8")
        rc = m.main(["--baseline", str(src), "--archive-dir", str(tmp_path / "a"),
                     "--internal-dir", str(tmp_path / "o")])
        assert rc == 2
        assert "契约校验不通过" in capsys.readouterr().err
