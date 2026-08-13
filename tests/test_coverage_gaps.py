"""任务五：补覆盖缺口。

排查发现的未直接覆盖函数（grep tests/ 为 0）：
- run_ut.read_select：被 ut_precheck/ut_execute 跨模块 import，无直接测试
- assemble_ddl.generate_create_table / generate_create_view：核心 DDL 构建器，
  仅经 generate_ddl 间接覆盖，补直接测试锁定行为

不连库/不读真实文件——用 tmp_path + dict 构造输入。
"""

from pathlib import Path

import pytest


# ============================================================
# 1. run_ut.read_select（跨模块 import，无直接测试）
# ============================================================

class TestReadSelect:
    """读 coder 产的 SELECT 文件：精确文件名优先，前缀确定匹配兜底，找不到返回空串。"""

    def test_exact_filename_preferred(self, tmp_path):
        from run_ut import read_select
        (tmp_path / "R0001.sql").write_text("SELECT 1;", encoding="utf-8")
        assert read_select(tmp_path, "R0001") == "SELECT 1;"

    def test_prefix_fallback_when_no_exact(self, tmp_path):
        """无精确 R0001.sql，但有 R0001_描述_loadmode.sql → 前缀确定匹配。"""
        from run_ut import read_select
        (tmp_path / "R0001_聚合_merge_into.sql").write_text("SELECT 2;", encoding="utf-8")
        assert read_select(tmp_path, "R0001") == "SELECT 2;"

    def test_exact_preferred_over_prefix(self, tmp_path):
        """精确文件名与前缀文件都在 → 精确优先（确定性，不靠 glob 模糊）。"""
        from run_ut import read_select
        (tmp_path / "R0001.sql").write_text("EXACT", encoding="utf-8")
        (tmp_path / "R0001_other.sql").write_text("PREFIX", encoding="utf-8")
        assert read_select(tmp_path, "R0001") == "EXACT"

    def test_not_found_returns_empty(self, tmp_path):
        from run_ut import read_select
        assert read_select(tmp_path, "R9999") == ""

    def test_does_not_match_other_rule_prefix(self, tmp_path):
        """不误匹配别的规则号前缀（R0001 不读 R0010_xxx）。"""
        from run_ut import read_select
        (tmp_path / "R0010_xxx.sql").write_text("OTHER", encoding="utf-8")
        assert read_select(tmp_path, "R0001") == ""


# ============================================================
# 2. assemble_ddl.generate_create_table（核心 DDL 构建器，直接测试）
# ============================================================

class TestGenerateCreateTable:
    """直接测 generate_create_table：CREATE TABLE + 字段 + 审计追加 + 分布键。"""

    def _rule(self, target="ods.dwb_test_f"):
        return {"target_table": target, "rule_name": "测试规则", "design_intent": "测试"}

    def _design(self):
        return {"audit_fields": {"del_flag": {"type": "nvarchar2(1)"},
                                 "crt_cycle_id": {"type": "bigint"}}}

    def _meta(self, schema="ods", table="dwb_test_f"):
        return {"target": {"f_table": {"schema": schema, "table": table, "cn": "测试"}}}

    def _tables(self, dist_key=None):
        return {
            "dwb_test_f": {
                "fields": [
                    {"target_field": "id", "field_type": "bigint", "field_comment": "ID"},
                    {"target_field": "amt", "field_type": "numeric(18,2)", "field_comment": "金额"},
                ],
                "distribution_key": dist_key or ["id"],
                "distribute_type": "HASH",
            }
        }

    def test_creates_table_with_fields_and_distribute_hash(self):
        from assemble_ddl import generate_create_table
        ddl = generate_create_table("R0001", self._rule(), self._design(),
                                    self._meta(), self._tables(dist_key=["id"]))
        assert "CREATE TABLE IF NOT EXISTS ods.dwb_test_f" in ddl
        # 业务字段都在
        assert "id" in ddl and "amt" in ddl
        # 审计字段追加（去重）
        assert "del_flag" in ddl and "crt_cycle_id" in ddl
        # 分布键
        assert "DISTRIBUTE BY HASH" in ddl and "id" in ddl

    def test_roundrobin_when_no_distribution_key(self):
        from assemble_ddl import generate_create_table
        tables = self._tables(dist_key=[])
        tables["dwb_test_f"]["distribute_type"] = "ROUNDROBIN"
        ddl = generate_create_table("R0001", self._rule(), self._design(),
                                    self._meta(), tables)
        assert "DISTRIBUTE BY ROUNDROBIN" in ddl

    def test_schema_fallback_from_meta_when_target_has_no_schema(self):
        """target_table 不带 schema 时，从 meta.target.f_table.schema 兜底。"""
        from assemble_ddl import generate_create_table
        # target_table 不含 schema（'dwb_test_f'），meta 给 schema
        rule = {"target_table": "dwb_test_f", "rule_name": "x", "design_intent": ""}
        ddl = generate_create_table("R0001", rule, self._design(), self._meta(schema="dws"))
        assert "dws.dwb_test_f" in ddl

    def test_audit_not_duplicated_when_already_in_fields(self):
        """审计字段已在业务字段里 → 不重复追加。"""
        from assemble_ddl import generate_create_table
        tables = self._tables()
        # 把 del_flag 放进业务字段
        tables["dwb_test_f"]["fields"].append(
            {"target_field": "del_flag", "field_type": "nvarchar2(1)", "field_comment": ""})
        ddl = generate_create_table("R0001", self._rule(), self._design(),
                                    self._meta(), tables)
        # del_flag 只应出现一次（字段名行）
        assert ddl.count("del_flag") == 1
