"""assemble_ddl_opt 测试：ALTER 变更单 + 全量 DDL + 差异审计（docs/specs/opt/05 §七）。"""
import json
from pathlib import Path

import pytest

from assemble_ts_opt import apply_decisions
from assemble_ddl_opt import build_alter_ddl, declared_additions_by_table, audit_full_ddl, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def pair():
    demo = json.loads((FIXTURES / "baseline_ts_dwb_trade_order_d.json").read_text(encoding="utf-8"))
    b = demo
    dec = {"change_type": "add_field", "backfill": "pending", "fields": [{
        "field": "channel_name", "target_table": "dwb_trade_order_d",
        "placed_rules": ["R0002"], "intermediate_tables": ["tmp_trade_order"],
        "field_type": "VARCHAR(64)", "field_comment": "渠道名称",
        "design_logic": "x", "transform_type": "direct", "source": {},
        "new_joins": []}]}
    # 中间表也要落位该字段（否则 fence 漏改）——decisions 上下两处都放
    dec["fields"][0]["placed_rules"] = ["R0001", "R0002"]
    v2 = apply_decisions(b, dec)
    # 测 I 视图重建路径：补 i_view 元数据（demo 契约未带）
    v2["meta"]["target"]["i_view"] = {"schema": "dws", "table": "dwb_trade_order_i", "cn": "订单"}
    return b, v2


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
        assert not (tmp_path / "ddl_full").exists(), "全量 DDL 退役（ts 可再生投影）"
        # I 视图重建：meta 有 i_view 时产出
        assert (tmp_path / "ddl/create_or_replace_view_dwb_trade_order_i.sql").exists(), \
            "F 表加列后 I 视图镜像须同步（语法结构决定的真交付物）"


class TestAudit:
    def test_clean_pass(self, pair):
        b, v2 = pair
        assert audit_full_ddl(b, v2) == []

    def test_smuggled_column_detected(self, pair):
        import copy
        b, v2 = copy.deepcopy(pair)  # 不原地改 module fixture（残留污染后续用例）
        v2["tables"]["dwb_trade_order_d"]["fields"].append(
            {"target_field": "smuggler", "field_type": "INT", "field_comment": ""})
        problems = audit_full_ddl(b, v2)
        assert any("smuggler" in p for p in problems)

    def test_removed_column_detected(self, pair):
        import copy
        b, v2 = copy.deepcopy(pair)  # 不原地改 module fixture（残留污染后续用例）
        v2["tables"]["dwb_trade_order_d"]["fields"] = [
            f for f in v2["tables"]["dwb_trade_order_d"]["fields"]
            if f["target_field"] != "cust_id"]
        problems = audit_full_ddl(b, v2)
        assert any("cust_id" in p and "不许删列" in p for p in problems)


class TestAuditBackfill:
    """opt 存量审计补齐（2026-09-15 定调：底层标准化非资产变更）。"""

    def test_audit_gap_goes_into_alter(self, pair, tmp_path):
        """原始 baseline 物理缺审计列 → 变更单自动 ADD COLUMN（不占 change 声明）。"""
        import copy
        b, v2 = copy.deepcopy(pair)  # module fixture 被先跑用例原地改过（smuggler 残留）——深拷贝隔离
        # 构造物理缺口：baseline tables 去掉全部审计列（旧档形态）
        from dws_standards import STANDARD_AUDIT_NAMES
        for tcfg in b.get("tables", {}).values():
            tcfg["fields"] = [f for f in tcfg.get("fields", [])
                              if str(f.get("target_field", "")).lower() not in STANDARD_AUDIT_NAMES]
        bp = tmp_path / "b.json"; vp = tmp_path / "v2.json"
        bp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        vp.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        from assemble_ddl_opt import main
        rc = main(["--ts-v2", str(vp), "--ts-baseline", str(bp), "--outdir", str(tmp_path)])
        assert rc == 0, "审计补齐是底层标准——对称 normalize 后围栏式校验不该拦"
        alter = (tmp_path / "ddl/alter_table_dwb_trade_order_d.sql").read_text(encoding="utf-8")
        assert "del_flag" in alter and "ADD COLUMN del_flag" in alter


class TestModifyTypeDdl:
    """场景 B（2026-10-22）：类型修改进 ALTER 变更单（DWS MODIFY 语法）。"""

    def test_rollback_generated_existing_table(self, pair, tmp_path):
        """回退=变更的逆（2026-11-04）：存量表 TRUNCATE+列级结构逆；档案零回退
        （产物只在 build 现场目录）。"""
        from assemble_ddl_opt import build_rollback_ddl
        b, v2 = pair
        bp = tmp_path / "b.json"; vp = tmp_path / "v2.json"
        bp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        vp.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        rc = main(["--ts-v2", str(vp), "--ts-baseline", str(bp), "--outdir", str(tmp_path)])
        assert rc == 0
        rb = tmp_path / "ddl_rollback" / "rollback_alter_dwb_trade_order_d.sql"
        assert rb.exists()
        text = rb.read_text(encoding="utf-8")
        # 2026-11-05 用户定调：交付件=纯 DDL 逆——TRUNCATE 是 UT 执行动作不进脚本
        assert "TRUNCATE TABLE" not in text   # 纯 DDL 逆（注释提及该词不算）
        assert "ALTER TABLE dws.dwb_trade_order_d DROP COLUMN" in text   # 列级逆非整表
        assert "DROP TABLE" not in text                                   # 存量表绝不整表 DROP
        assert (tmp_path / "ddl_rollback" / "rollback_alter_tmp_trade_order.sql").exists()

    def test_rollback_new_table_drop(self):
        from assemble_ddl_opt import build_rollback_ddl
        sql = build_rollback_ddl("dws", "tmp_new", [], [], is_new_table=True)
        assert "DROP TABLE IF EXISTS dws.tmp_new;" in sql
        assert "TRUNCATE" not in sql

    def test_rollback_modify_restores_old_type(self):
        from assemble_ddl_opt import build_rollback_ddl
        sql = build_rollback_ddl("dws", "t1", [], [{"field": "c1", "old_type": "VARCHAR(32)",
                                                    "new_type": "VARCHAR(64)"}])
        assert "ALTER TABLE dws.t1 MODIFY (c1 VARCHAR(32));" in sql   # 逆=还原旧类型

    def test_alter_contains_modify(self):
        from assemble_ddl_opt import build_alter_ddl
        sql = build_alter_ddl("dws", "t1", [{"field": "c1", "field_type": "varchar(64)"}],
                              modifies=[{"field": "order_id", "old_type": "varchar(64)",
                                         "new_type": "varchar(128)"}])
        assert "ALTER TABLE dws.t1 ADD COLUMN c1 varchar(64);" in sql
        assert "ALTER TABLE dws.t1 MODIFY (order_id varchar(128));" in sql
        assert "类型修改 1 列" in sql

    def test_comments_are_block_style(self):
        """SQL 注释一律 /* */（2026-11-10 准则入册）：交付件头注释禁 -- 行注释。"""
        from assemble_ddl_opt import build_alter_ddl, build_rollback_ddl
        for sql in (build_alter_ddl("dws", "t1", [{"field": "c1", "field_type": "varchar(64)"}]),
                    build_rollback_ddl("dws", "t1", [{"field": "c1", "field_type": "varchar(64)"}]),
                    build_rollback_ddl("dws", "t_new", [], is_new_table=True)):
            assert "/*" in sql
            for line in sql.splitlines():
                stripped = line.strip()
                assert not (stripped.startswith("--") or "  -- " in line), \
                    f"交付 SQL 禁 -- 行注释: {line}"
