#!/usr/bin/env python3
"""
preprocess 预检校验的测试用例。
验证各种错误场景能否被校验规则正确拦截。

运行：python -m pytest tests/test_precheck_rules.py -v
"""

import sys
import pytest
from pathlib import Path

# 添加 skill references 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "dws-design" / "references"))
from preprocess import precheck, PrecheckResult


def _make_rs_input(field_mappings, source_tables=None, schedule=None):
    """构造最小 rs_input 用于测试。"""
    return {
        "meta": {
            "target": {"schema": "test_schema", "table": "test_table", "cn": "测试表", "description": ""},
            "grain": "测试粒度",
        },
        "source_tables": source_tables or [
            {"source_schema": "s", "source_table": "src_t", "source_alias": "t", "join_condition": "主表"}
        ],
        "field_mappings": field_mappings,
        "schedule": schedule or {"frequency": "T+1", "strategy": "全量", "upstream": [{"table": "x", "task": "t1"}]},
    }


# ============================================================
# 正常用例：标准数据应该全过
# ============================================================

class TestNormalCases:
    """标准数据，预检应通过（0错误0警告或仅上游警告）。"""

    def test_all_valid(self):
        """所有字段合法：直接复制+数据加工+赋值。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "-", "source_column": "src_f1", "source_alias": "t"},
            {"target_column": "f2", "transform_rule": "数据加工", "transform_detail": "对金额求和", "source_column": "src_f2", "source_alias": "t"},
            {"target_column": "f3", "transform_rule": "赋值", "transform_detail": "'N'", "source_column": "", "source_alias": ""},
        ])
        result = precheck(rs_input)
        assert result.return_code == 0, f"应通过，但有：{result.errors + result.warnings}"


# ============================================================
# 映射规则类型校验
# ============================================================

class TestRuleTypeValidation:
    """映射规则类型不合法。"""

    def test_invalid_rule_type(self):
        """映射规则值不在四种合法类型里。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直取", "transform_detail": "-", "source_column": "src_f1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("不合法" in e for e in result.errors)

    def test_missing_rule(self):
        """映射规则为空。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "", "transform_detail": "", "source_column": "src_f1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("缺少映射规则" in e for e in result.errors)


# ============================================================
# 直接复制：不该有表达式
# ============================================================

class TestDirectCopyRule:
    """直接复制的交叉校验。"""

    def test_direct_copy_with_expression_warns(self):
        """直接复制但有表达式 → 警告。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "有加工逻辑", "source_column": "src_f1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert any("直接复制" in w and "映射表达式" in w for w in result.warnings)

    def test_direct_copy_without_source_errors(self):
        """直接复制但没有来源字段 → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "-", "source_column": "", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("缺少来源字段" in e for e in result.errors)


# ============================================================
# 数据加工：必须有表达式
# ============================================================

class TestDataProcessingRule:
    """数据加工的交叉校验。"""

    def test_processing_without_expression_errors(self):
        """数据加工但表达式为空 → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "数据加工", "transform_detail": "", "source_column": "src_f1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("映射表达式为空" in e for e in result.errors)

    def test_processing_with_dash_expression_errors(self):
        """数据加工但表达式是'-' → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "数据加工", "transform_detail": "-", "source_column": "src_f1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("映射表达式为空" in e for e in result.errors)


# ============================================================
# 赋值：必须有表达式
# ============================================================

class TestAssignRule:
    """赋值的交叉校验。"""

    def test_assign_without_expression_errors(self):
        """赋值但表达式为空 → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "赋值", "transform_detail": "", "source_column": "", "source_alias": ""},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("映射表达式为空" in e for e in result.errors)

    def test_assign_with_expression_passes(self):
        """赋值且有表达式 → 通过。"""
        rs_input = _make_rs_input([
            {"target_column": "del_flag", "transform_rule": "赋值", "transform_detail": "'N'", "source_column": "", "source_alias": ""},
        ])
        result = precheck(rs_input)
        assert result.return_code == 0


# ============================================================
# 目标字段重复
# ============================================================

class TestDuplicateFields:
    """目标字段重复检查。"""

    def test_duplicate_target_field(self):
        """同一目标字段出现两次 → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "-", "source_column": "s1", "source_alias": "t"},
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "-", "source_column": "s2", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("重复" in e for e in result.errors)


# ============================================================
# 别名一致性
# ============================================================

class TestAliasConsistency:
    """属性级别名必须在实体级存在。"""

    def test_unknown_alias_errors(self):
        """属性级用了实体级没有的别名 → 错误。"""
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "直接复制", "transform_detail": "-", "source_column": "s1", "source_alias": "x"},
        ])
        result = precheck(rs_input)
        assert result.return_code == 2
        assert any("不存在" in e for e in result.errors)


# ============================================================
# 模糊术语检查
# ============================================================

class TestFuzzyTerms:
    """映射表达式含模糊术语 → 警告。"""

    def test_fuzzy_term_warns(self):
        rs_input = _make_rs_input([
            {"target_column": "f1", "transform_rule": "数据加工", "transform_detail": "对金额等等求和", "source_column": "s1", "source_alias": "t"},
        ])
        result = precheck(rs_input)
        assert any("模糊术语" in w for w in result.warnings)
