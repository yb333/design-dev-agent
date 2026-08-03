"""
preprocess.py 核心逻辑测试。

重点测两类逻辑（build_rs_input 内部）：
1. 目标表后缀 -> f_table / i_view 推导
2. RS vs mapping 的 schema/table 校验分级（阻断 vs 告警 vs 正常）

测试数据全部用 dict 构造，不读真实 xlsx；build_rs_input 可直接 import 调用
（mapping_raw 和 rs_data 都是 dict，不依赖 ExcelMappingParser）。
"""

import pytest

# preprocess 通过 conftest.py 把 DESIGN_REFS 加入 sys.path 后可直接 import
from preprocess import build_rs_input


# ============================================================
# 工具：构造 mapping_raw / rs_data 的最小 dict
# ============================================================

def _mapping_raw(target_schema="dws", table="dwb_test_i", cn="测试表"):
    """构造 build_rs_input 第一参数 mapping_raw 的最小形态。

    build_rs_input 内部会先调 slim_mapping_data 做字段精简，但 schema/table/cn
    这几个顶层字段直接从 mapping_raw 读取，所以这里只需保证这几个字段在即可。
    """
    return {
        "target_schema": target_schema,
        "target_table": table,
        "target_table_cn": cn,
        "source_tables": [],
        "field_mappings": [],
    }


def _rs_data(schema="", table="", cn=""):
    """构造 build_rs_input 第二参数 rs_data 的最小形态（meta.target 部分）。"""
    return {
        "meta": {
            "target": {"schema": schema, "table": table, "cn": cn},
        },
    }


def _f_table(result):
    return result["meta"]["target"]["f_table"]["table"]


def _i_view(result):
    return result["meta"]["target"]["i_view"]["table"]


# ============================================================
# 1. 目标表后缀 -> f_table / i_view 推导
# ============================================================

class TestSuffixDerivation:
    """测 build_rs_input 里 _i / _f / _d / 无后缀 的推导规则。"""

    def test_i_suffix(self):
        """_i 结尾 -> f_table=_f, i_view=_i"""
        r = build_rs_input(_mapping_raw(table="dwb_test_i"), _rs_data())
        assert _f_table(r) == "dwb_test_f"
        assert _i_view(r) == "dwb_test_i"

    def test_f_suffix(self):
        """_f 结尾 -> f_table=_f, i_view=_i"""
        r = build_rs_input(_mapping_raw(table="dwb_test_f"), _rs_data())
        assert _f_table(r) == "dwb_test_f"
        assert _i_view(r) == "dwb_test_i"

    def test_d_suffix(self):
        """_d 结尾（无标准后缀）-> f_table=原名, i_view=原名_i"""
        r = build_rs_input(_mapping_raw(table="dim_test_d"), _rs_data())
        assert _f_table(r) == "dim_test_d"
        assert _i_view(r) == "dim_test_d_i"

    def test_no_suffix(self):
        """无后缀 -> f_table=原名, i_view=原名_i"""
        r = build_rs_input(_mapping_raw(table="dim_test"), _rs_data())
        assert _f_table(r) == "dim_test"
        assert _i_view(r) == "dim_test_i"


# ============================================================
# 2. schema / table 校验分级
# ============================================================

class TestValidationGrading:
    """测 build_rs_input 里的校验分级逻辑。"""

    def test_both_no_schema_blocks(self, capsys):
        """两边都没写 schema -> 阻断（sys.exit 1）"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="", table="dwb_test_i"),
                _rs_data(schema="", table="dwb_test_i"),
            )
        assert exc.value.code == 1
        # 错误信息应落到 stderr
        err = capsys.readouterr().err
        assert "schema" in err
        assert "都没写" in err

    def test_schema_mismatch_blocks(self, capsys):
        """两边 schema 不一致 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table="dwb_test_i"),
                _rs_data(schema="ods", table="dwb_test_i"),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "schema 不一致" in err

    def test_mapping_only_schema_warns(self, capsys):
        """mapping 有 schema、RS 没有 -> 告警但不阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" in out and "RS 没写 schema" in out
        # 最终 schema 取 mapping 的
        assert r["meta"]["target"]["f_table"]["schema"] == "dws"

    def test_rs_only_schema_warns(self, capsys):
        """RS 有 schema、mapping 没有 -> 告警但不阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="", table="dwb_test_i"),
            _rs_data(schema="ods", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" in out and "mapping 没写 schema" in out
        # 最终 schema 取 RS 的
        assert r["meta"]["target"]["f_table"]["schema"] == "ods"

    def test_schema_consistent_passes(self, capsys):
        """两边 schema 一致 -> 正常，无告警无阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="dws", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" not in out
        assert r["meta"]["target"]["f_table"]["schema"] == "dws"
        assert _f_table(r) == "dwb_test_f"

    def test_both_no_table_blocks(self, capsys):
        """两边都没写表名 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table=""),
                _rs_data(schema="dws", table=""),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "表名" in err and "都没写" in err

    def test_table_mismatch_blocks(self, capsys):
        """两边表名不一致 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table="dwb_a_i"),
                _rs_data(schema="dws", table="dwb_b_i"),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "表名不一致" in err


# ============================================================
# 3. 与 conftest 工厂函数集成（确保 make_rs_input 推导一致）
# ============================================================

class TestFactoryIntegration:
    """验证 conftest.make_rs_input 的推导与 build_rs_input 行为一致。"""

    def test_factory_i_suffix_matches(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i")
        assert rs["meta"]["target"]["f_table"]["table"] == "dwb_test_f"
        assert rs["meta"]["target"]["i_view"]["table"] == "dwb_test_i"

    def test_factory_f_suffix_matches(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_f")
        assert rs["meta"]["target"]["f_table"]["table"] == "dwb_test_f"
        assert rs["meta"]["target"]["i_view"]["table"] == "dwb_test_i"

    def test_factory_has_audit_fields(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i")
        targets = {f["target_column"] for f in rs["field_mappings"]}
        assert {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"} <= targets

    def test_factory_no_audit(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i", has_audit=False)
        targets = {f["target_column"] for f in rs["field_mappings"]}
        assert "del_flag" not in targets
        assert targets == {"id"}
