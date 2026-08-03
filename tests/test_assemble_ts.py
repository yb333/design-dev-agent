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
