"""
目标表 schema/table 校验分级测试。

测 preprocess.py 的 validate_target_table（从 build_rs_input 抽出的独立函数）。
该函数只依赖 4 个字符串入参，返回 (final_schema, final_table, errors, warnings)，
不依赖 ExcelMappingParser / xlsx 文件，可直接调用。

校验分级（schema 和 table 各自独立判定）：
- 两边都没写 → errors 非空（阻断）
- 两边都写了但不一致 → errors 非空（阻断）
- 一边写了一边没写 → warnings 非空，errors 为空（互补，不阻断）
- 两边都写了且一致 → errors 和 warnings 都为空

同时验证 build_rs_input 调用 validate_target_table 后行为不变：
告警走 stdout、阻断走 sys.exit(1)。
"""

import pytest

from preprocess import validate_target_table, build_rs_input


# ============================================================
# 1. 独立函数：4 种校验分级场景
# ============================================================

class TestValidateTargetTableGrading:
    def test_both_empty_blocks(self):
        """两边都没写 schema 和 table → errors 非空（阻断）"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="", rs_table="", mapping_schema="", mapping_table=""
        )
        assert len(errors) >= 2, f"schema 和 table 都缺应各报一个 error: {errors}"
        # schema 和 table 都应报"都没写"
        assert any("schema" in e and "都没写" in e for e in errors)
        assert any("表名" in e and "都没写" in e for e in errors)
        # 没有告警（是阻断不是告警）
        assert warnings == []
        # 互补后还是空
        assert final_schema == ""
        assert final_table == ""

    def test_mismatch_blocks(self):
        """两边 schema 不一致 → errors 非空（阻断）"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="ods", rs_table="t_i",
            mapping_schema="dws", mapping_table="t_i"
        )
        assert any("schema 不一致" in e for e in errors), \
            f"schema 不一致应报阻断: {errors}"
        # table 一致 → 不报错
        assert not any("表名" in e for e in errors)
        assert warnings == []

    def test_table_mismatch_blocks(self):
        """两边 table 不一致 → errors 非空（阻断）"""
        _, _, errors, _ = validate_target_table(
            rs_schema="dws", rs_table="a_i",
            mapping_schema="dws", mapping_table="b_i"
        )
        assert any("表名不一致" in e for e in errors), \
            f"表名不一致应报阻断: {errors}"
        # schema 一致 → 不报错
        assert not any("schema" in e for e in errors)

    def test_mapping_only_warns(self):
        """mapping 有 schema/table、RS 没有 → warnings 非空，不阻断"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="", rs_table="",
            mapping_schema="dws", mapping_table="dwb_test_i"
        )
        assert errors == [], f"一边有不应阻断: {errors}"
        assert len(warnings) == 2, f"schema 和 table 各应告警一次: {warnings}"
        assert any("RS 没写 schema" in w for w in warnings)
        assert any("RS 没写表名" in w for w in warnings)
        # 互补后用 mapping 的值
        assert final_schema == "dws"
        assert final_table == "dwb_test_i"

    def test_rs_only_warns(self):
        """RS 有 schema/table、mapping 没有 → warnings 非空，不阻断"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="ods", rs_table="dim_test_i",
            mapping_schema="", mapping_table=""
        )
        assert errors == []
        assert len(warnings) == 2
        assert any("mapping 没写 schema" in w for w in warnings)
        assert any("mapping 没写表名" in w for w in warnings)
        # 互补后用 RS 的值
        assert final_schema == "ods"
        assert final_table == "dim_test_i"

    def test_both_consistent_passes(self):
        """两边一致 → errors 和 warnings 都为空"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="dws", rs_table="dwb_test_i",
            mapping_schema="dws", mapping_table="dwb_test_i"
        )
        assert errors == [], f"一致不应报错: {errors}"
        assert warnings == [], f"一致不应告警: {warnings}"
        assert final_schema == "dws"
        assert final_table == "dwb_test_i"


# ============================================================
# 2. schema 和 table 独立判定（混合场景）
# ============================================================

class TestSchemaTableIndependentGrading:
    def test_schema_consistent_but_table_missing_warns_on_table_only(self):
        """schema 一致、table 两边都没写 → table 报阻断，schema 正常"""
        _, _, errors, warnings = validate_target_table(
            rs_schema="dws", rs_table="",
            mapping_schema="dws", mapping_table=""
        )
        # table 缺 → 阻断
        assert any("表名" in e and "都没写" in e for e in errors)
        # schema 一致 → 无 error 无 warning
        assert not any("schema" in e for e in errors)
        assert not any("schema" in w for w in warnings)

    def test_schema_mismatch_but_table_consistent(self):
        """schema 不一致、table 一致 → schema 报阻断，table 正常"""
        _, _, errors, _ = validate_target_table(
            rs_schema="ods", rs_table="t_i",
            mapping_schema="dws", mapping_table="t_i"
        )
        assert any("schema 不一致" in e for e in errors)
        assert not any("表名" in e for e in errors)

    def test_schema_rs_only_table_mapping_only_both_warn(self):
        """schema 在 RS、table 在 mapping → 两个都告警，都不阻断"""
        final_schema, final_table, errors, warnings = validate_target_table(
            rs_schema="ods", rs_table="",
            mapping_schema="", mapping_table="dwb_test_i"
        )
        assert errors == []
        assert len(warnings) == 2
        # 互补后 schema 用 RS 的，table 用 mapping 的
        assert final_schema == "ods"
        assert final_table == "dwb_test_i"


# ============================================================
# 3. 集成：build_rs_input 调 validate_target_table 后行为不变
# ============================================================

class TestBuildRsInputUsesValidation:
    """验证 build_rs_input 调 validate_target_table 后，告警/阻断行为和以前一致。"""

    @staticmethod
    def _mapping_raw(schema="", table="dwb_test_i"):
        return {
            "target_schema": schema, "target_table": table,
            "target_table_cn": "测试表",
            "source_tables": [], "field_mappings": [],
        }

    @staticmethod
    def _rs_data(schema="", table=""):
        return {"meta": {"target": {"schema": schema, "table": table, "cn": ""}}}

    def test_blocking_exits_with_code_1(self, capsys):
        """两边都没写 → build_rs_input 应 sys.exit(1)"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(self._mapping_raw(schema="", table=""),
                           self._rs_data(schema="", table=""))
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "schema" in err and "都没写" in err

    def test_warning_goes_to_stdout_no_exit(self, capsys):
        """一边有一边没有 → 告警进 stdout，不 exit，结果用互补值"""
        result = build_rs_input(
            self._mapping_raw(schema="dws", table="dwb_test_i"),
            self._rs_data(schema="", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" in out
        assert "RS 没写 schema" in out
        # 互补后 schema 取 mapping 的
        assert result["meta"]["target"]["f_table"]["schema"] == "dws"

    def test_consistent_no_warning_no_exit(self, capsys):
        """两边一致 → 无告警、无 exit"""
        result = build_rs_input(
            self._mapping_raw(schema="dws", table="dwb_test_i"),
            self._rs_data(schema="dws", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" not in out
        assert result["meta"]["target"]["f_table"]["schema"] == "dws"
