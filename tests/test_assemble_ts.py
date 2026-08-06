"""assemble_ts.py 的 build_rule 测试。

重点覆盖 source_tables 的"留空兜底"行为：
designer 在 design_decisions 里把 source_aliases 留空（或省略）时，
脚本应默认用 rs_input 的所有 source_tables 补全（见 design_decisions 模板注释）。

回归背景：build_rule 原先只在 source_aliases 非空时填 source_tables，
留空时产出 []，导致 check_sql 报"SELECT 引用了不在 ts.json source_tables 里的表"。
"""

import pytest

from assemble_ts import build_rule


def _rs_sources():
    """构造 rs_input 风格的 source_tables（按别名可寻）。"""
    return [
        {"source_alias": "dpf", "source_schema": "sdinv", "source_table": "dwd_purchase_f"},
        {"source_alias": "dsf", "source_schema": "dim", "source_table": "dim_supplier_f"},
        {"source_alias": "dif", "source_schema": "sdinv", "source_table": "dwd_inventory_f"},
    ]


def test_source_aliases_empty_falls_back_to_all_rs_sources():
    """source_aliases 留空 -> 用 rs_input 全部 source_tables。"""
    rule, _ = build_rule({"rule_code": "R0001", "source_aliases": []}, {}, _rs_sources())
    tables = [s["table"] for s in rule["source_tables"]]
    assert tables == ["dwd_purchase_f", "dim_supplier_f", "dwd_inventory_f"]
    # schema/alias 也应补全
    assert rule["source_tables"][0] == {
        "schema": "sdinv", "table": "dwd_purchase_f", "alias": "dpf"}


def test_source_aliases_missing_falls_back_to_all_rs_sources():
    """source_aliases 键省略（None）-> 同样兜底。"""
    rule, _ = build_rule({"rule_code": "R0001"}, {}, _rs_sources())
    assert len(rule["source_tables"]) == 3


def test_source_aliases_explicit_only_lists_those():
    """designer 显式列了别名 -> 只产出这些（不兜底）。"""
    rule, _ = build_rule(
        {"rule_code": "R0001", "source_aliases": ["dpf"]}, {}, _rs_sources())
    assert len(rule["source_tables"]) == 1
    assert rule["source_tables"][0]["table"] == "dwd_purchase_f"


def test_source_aliases_empty_and_no_rs_sources_yields_empty():
    """两边都空 -> source_tables 为 []（不报错）。"""
    rule, _ = build_rule({"rule_code": "R0001", "source_aliases": []}, {}, [])
    assert rule["source_tables"] == []


# ============================================================
# validate_decisions 测试：多步骤模型下的字段分配校验
# ============================================================

from assemble_ts import validate_decisions


def _field_map(*names):
    """构造 field_map：{字段名: field_mapping记录}。"""
    return {n: {"target_column": n} for n in names}


class TestValidateDecisions:
    """多步骤模型：同字段可跨表，同表内不能重复。"""

    def test_simple_single_rule_passes(self):
        """简单单规则：覆盖所有字段 → 通过。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id", "name"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        assert errors == []

    def test_same_field_across_intermediate_and_target_passes(self):
        """★ 同字段在中间表+目标表各一份 → 不报错（多步骤核心场景）。

        user_id 在 tmp1 和目标表都有——这是正常的字段透传，不是重复分配。
        """
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "tmp1",
             "target_role": "intermediate", "field_targets": ["user_id", "total_amt"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["user_id", "total_amt", "name"]},
        ]}
        errors = validate_decisions(decisions, _field_map("user_id", "total_amt", "name"))
        assert errors == [], f"同字段跨表不应报错: {errors}"

    def test_same_field_same_table_two_rules_reports(self):
        """同一张表被两个规则声明同一字段 → 报错（真重复）。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]},
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        dup_errors = [e for e in errors if "重复" in e]
        assert dup_errors, f"同表重复应报错: {errors}"

    def test_target_not_covering_all_fields_reports(self):
        """目标表规则没覆盖 rs_input 所有字段 → 报缺失。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name", "amount"))
        missing_errors = [e for e in errors if "没有分配" in e]
        assert missing_errors, f"应报字段缺失: {errors}"
        assert "name" in missing_errors[0] and "amount" in missing_errors[0]

    def test_intermediate_not_covering_all_is_ok(self):
        """中间表字段不要求覆盖 rs_input（中间表可能有 designer 自建字段）。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "tmp1",
             "target_role": "intermediate", "field_targets": ["user_id"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["user_id", "name", "amount"]},
        ]}
        errors = validate_decisions(decisions, _field_map("user_id", "name", "amount"))
        assert errors == [], f"中间表不要求全覆盖: {errors}"

    def test_field_not_in_rs_input_reports(self):
        """field_targets 里有 rs_input 找不到的字段 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id", "nonexistent"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        not_found = [e for e in errors if "找不到" in e]
        assert not_found, f"应报找不到字段: {errors}"

    def test_empty_field_targets_reports(self):
        """规则 field_targets 为空 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": []}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert any("为空" in e for e in errors)
