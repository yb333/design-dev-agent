"""tables 段结构测试。

验证字段定义从 rules 搬到 tables 后的核心行为：
- tables 段正确生成（每表有 type/distribution_key/fields）
- rules 只有 field_targets + field_logics，不再有 fields
- 多规则写同表时表只出现一次
- 审计字段补充到目标表的 fields
- 分布键 per-table（decisions.tables 声明优先，全局兜底）
"""
import pytest

# conftest 已把 design scripts 加入 sys.path
from assemble_ts import assemble_ts, build_tables, infer_logical_group


def _make_rs_input(fields):
    """造最小 rs_input，fields 是 target_column 列表"""
    return {
        "field_mappings": [
            {
                "target_column": name,
                "target_type": "varchar(100)",
                "target_column_cn": f"{name}中文名",
                "source_column": f"src_{name}",
                "source_alias": "a",
                "source_table": "ods_src_f",
                "transform_rule": "直接复制",
            }
            for name in fields
        ],
        "source_tables": [{"source_schema": "ods", "source_table": "ods_src_f", "source_alias": "a"}],
        "meta": {"target": {"schema": "dws", "table": "dwb_test_f"}},
    }


def _make_decisions(rules_spec, tables_spec=None, dist_key=None):
    """造最小 decisions。
    rules_spec: [(code, target_table, field_targets, field_logics)]
    """
    dec = {
        "rules": [
            {
                "rule_code": code,
                "rule_name": f"规则{code}",
                "target_table": target,
                "field_targets": targets,
                "field_logics": logics,
            }
            for code, target, targets, logics in rules_spec
        ],
    }
    if tables_spec:
        dec["tables"] = tables_spec
    if dist_key:
        dec["distribution_key"] = dist_key
    return dec


class TestTablesGeneration:
    """tables 段生成"""

    def test_single_table(self):
        """单规则单表 → tables 有 1 张"""
        rs = _make_rs_input(["a", "b", "c"])
        dec = _make_decisions([("R0001", "dwb_test_f", ["a", "b", "c"], {})])
        ts, _, _ = assemble_ts(rs, dec)
        assert "dwb_test_f" in ts["tables"]
        assert ts["tables"]["dwb_test_f"]["type"] == "target"

    def test_multi_table_with_tmp(self):
        """多规则带中间表 → tables 有 2 张"""
        rs = _make_rs_input(["a", "b", "c", "d"])
        dec = _make_decisions([
            ("R0001", "dwb_test_tmp1", ["a", "b"], {}),
            ("R0002", "dwb_test_f", ["c", "d"], {}),
        ])
        ts, _, _ = assemble_ts(rs, dec)
        assert "dwb_test_tmp1" in ts["tables"]
        assert "dwb_test_f" in ts["tables"]
        assert ts["tables"]["dwb_test_tmp1"]["type"] == "intermediate"
        assert ts["tables"]["dwb_test_f"]["type"] == "target"

    def test_fields_in_tables_not_rules(self):
        """字段定义在 tables，不在 rules"""
        rs = _make_rs_input(["a", "b"])
        dec = _make_decisions([("R0001", "dwb_test_f", ["a", "b"], {})])
        ts, _, _ = assemble_ts(rs, dec)
        # tables 有字段（2 业务 + 4 审计自动补充 = 6）
        all_fields = ts["tables"]["dwb_test_f"]["fields"]
        business_fields = [f for f in all_fields if f["target_field"] in ("a", "b")]
        assert len(business_fields) == 2
        # rules 没有 fields，有 field_targets
        assert "fields" not in ts["rules"]["R0001"]
        assert "field_targets" in ts["rules"]["R0001"]
        assert set(ts["rules"]["R0001"]["field_targets"]) == {"a", "b"}

    def test_field_logics_stay_in_rules(self):
        """加工口径留在 rules 的 field_logics"""
        rs = _make_rs_input(["a", "b"])
        dec = _make_decisions([("R0001", "dwb_test_f", ["a", "b"], {"b": "汇总求和"})])
        ts, _, _ = assemble_ts(rs, dec)
        assert ts["rules"]["R0001"]["field_logics"]["b"] == "汇总求和"

    def test_distribution_key_per_table(self):
        """per-table 分布键（decisions.tables 声明）"""
        rs = _make_rs_input(["a", "b"])
        dec = _make_decisions(
            [("R0001", "dwb_test_f", ["a", "b"], {})],
            tables_spec={"dwb_test_f": {"distribution_key": ["custom_key"]}},
        )
        ts, _, _ = assemble_ts(rs, dec)
        assert ts["tables"]["dwb_test_f"]["distribution_key"] == ["custom_key"]

    def test_distribution_key_global_fallback(self):
        """没填 tables.tables → 用旧版全局 distribution_key 兜底"""
        rs = _make_rs_input(["a", "b"])
        dec = _make_decisions(
            [("R0001", "dwb_test_f", ["a", "b"], {})],
            dist_key=["global_key"],
        )
        ts, _, _ = assemble_ts(rs, dec)
        assert ts["tables"]["dwb_test_f"]["distribution_key"] == ["global_key"]

    def test_different_dist_keys_per_table(self):
        """中间表和目标表分布键不同"""
        rs = _make_rs_input(["a", "b", "c"])
        dec = _make_decisions(
            [
                ("R0001", "dwb_test_tmp1", ["a"], {}),
                ("R0002", "dwb_test_f", ["b", "c"], {}),
            ],
            tables_spec={
                "dwb_test_tmp1": {"distribution_key": ["user_id"]},
                "dwb_test_f": {"distribution_key": ["order_id"]},
            },
        )
        ts, _, _ = assemble_ts(rs, dec)
        assert ts["tables"]["dwb_test_tmp1"]["distribution_key"] == ["user_id"]
        assert ts["tables"]["dwb_test_f"]["distribution_key"] == ["order_id"]

    def test_design_no_distribution_key(self):
        """design 段不再有 distribution_key"""
        rs = _make_rs_input(["a"])
        dec = _make_decisions([("R0001", "dwb_test_f", ["a"], {})])
        ts, _, _ = assemble_ts(rs, dec)
        assert "distribution_key" not in ts["design"]

    def test_view_not_in_tables(self):
        """I 视图不在 tables 段"""
        rs = _make_rs_input(["a"])
        dec = _make_decisions([("R0001", "dwb_test_f", ["a"], {})])
        ts, _, _ = assemble_ts(rs, dec)
        # I 视图名不在 tables
        assert "dwb_test_i" not in ts.get("tables", {})


class TestInferLogicalGroup:
    """逻辑集群推断"""

    def test_default(self):
        assert infer_logical_group("dws") == "LC_DW1"

    def test_drt_schema(self):
        assert infer_logical_group("dwr_dim_drt") == "gtoup_version1"

    def test_empty(self):
        assert infer_logical_group("") == "LC_DW1"
