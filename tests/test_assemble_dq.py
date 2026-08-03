"""
assemble_dq.py 的 generate_dq_sql 测试。

核心校验去重逻辑：
- RS 已有重复检查 → 不再标准生成"主键唯一性"
- RS 已有空值检查 → 不再标准生成"审计字段非空"
- RS 没覆盖的 → 补标准检查（主键唯一 / 审计非空 / 记录数）

另外覆盖目标表识别：
- _d 结尾目标表也能生成 DQ
- 中间表（tmp）不生成 DQ
- 视图步骤不生成 DQ

测试数据用 conftest.make_ts_json 工厂构造。
"""

import pytest

from assemble_dq import generate_dq_sql, _has_duplicate_check, _has_null_check
from conftest import make_ts_json


# ============================================================
# 1. 辅助：识别函数（_has_duplicate_check / _has_null_check）
# ============================================================

class TestRuleTypeDetectors:
    def test_has_duplicate_check_detects_chinese_keywords(self):
        """中文关键词（重复/唯一）能识别"""
        assert _has_duplicate_check([{"check_type": "重复数据检查", "rule_name": ""}])
        assert _has_duplicate_check([{"check_type": "", "rule_name": "唯一性校验"}])

    def test_has_duplicate_check_detects_english_keywords(self):
        """英文关键词（unique/duplicate）能识别"""
        assert _has_duplicate_check([{"check_type": "unique", "rule_name": ""}])
        assert _has_duplicate_check([{"check_type": "", "rule_name": "duplicate check"}])

    def test_has_duplicate_check_returns_false_when_absent(self):
        """没有重复检查 → False"""
        assert not _has_duplicate_check([{"check_type": "范围检查", "rule_name": "金额范围"}])
        assert not _has_duplicate_check([])

    def test_has_null_check_detects_keywords(self):
        """空值检查关键词识别"""
        assert _has_null_check([{"check_type": "空值检查", "rule_name": ""}])
        assert _has_null_check([{"check_type": "", "rule_name": "非空校验"}])
        assert _has_null_check([{"check_type": "not null", "rule_name": ""}])

    def test_has_null_check_returns_false_when_absent(self):
        """没有空值检查 → False"""
        assert not _has_null_check([{"check_type": "重复检查", "rule_name": ""}])
        assert not _has_null_check([])


# ============================================================
# 2. 去重逻辑：RS 有覆盖 → 不重复生成标准检查
# ============================================================

# TestDqDeduplication 已删除（去重逻辑废弃，标准DQ总是生成，定制DQ全交coder）


# ============================================================
# 3. RS 没覆盖的 → 补全部标准检查
# ============================================================

class TestDqStandardFallback:
    def test_dq_supplements_all_standard_checks_when_rs_empty(self):
        """RS 没有 DQ → 补全部标准检查（主键唯一 + 审计非空 + 记录数）"""
        ts = make_ts_json(table="dwb_test_i", dq_rules=[])
        dqs = generate_dq_sql(ts)

        assert len(dqs) == 1
        content = list(dqs.values())[0]

        # 三个标准检查都应有
        assert "主键唯一性" in content
        assert "审计字段非空" in content
        assert "total_count" in content
        # 没有 RS DQ 区块
        assert "RS 提供的 DQ" not in content


# ============================================================
# 4. 目标表识别：_d 能生成、tmp 不生成
# ============================================================

class TestDqTargetSelection:
    def test_d_table_generates_dq(self):
        """_d 结尾目标表（明细层）也能生成 DQ"""
        rules = {
            "R0001": {
                "rule_name": "明细规则", "scenario": "default", "exec_sequence": 1,
                "target_table": "dim_test_d", "is_view_step": False,
                "design_intent": "明细层", "source_tables": [],
                "fields": [
                    {"target_field": "id", "field_type": "bigint", "field_comment": "ID",
                     "transform_type": "direct", "source_fields": [], "design_logic": ""},
                    {"target_field": "del_flag", "field_type": "NVARCHAR(1)",
                     "field_comment": "删除", "transform_type": "assign",
                     "source_fields": [], "design_logic": ""},
                ],
                "field_count": 2,
            }
        }
        ts = make_ts_json(table="dim_test_d", rules=rules)
        # 让 meta.target.f_table.table 与目标表名一致（_d 不是 _f/_i）
        ts["meta"]["target"]["f_table"]["table"] = "dim_test_d"

        dqs = generate_dq_sql(ts)
        assert len(dqs) == 1, f"_d 目标表应生成 DQ，实际: {list(dqs.keys())}"
        assert "dq_dim_test_d.sql" in dqs
        content = list(dqs.values())[0]
        assert "total_count" in content

    def test_tmp_table_does_not_generate_dq(self):
        """中间表（tmp）不生成 DQ"""
        rules = {
            "R0001": {
                "rule_name": "中间表规则", "scenario": "default", "exec_sequence": 1,
                "target_table": "tmp_order_agg", "is_view_step": False,
                "design_intent": "中间收敛", "source_tables": [],
                "fields": [
                    {"target_field": "id", "field_type": "bigint", "field_comment": "ID",
                     "transform_type": "direct", "source_fields": [], "design_logic": ""},
                ],
                "field_count": 1,
            }
        }
        ts = make_ts_json(table="tmp_order_agg", rules=rules)
        ts["meta"]["target"]["f_table"]["table"] = "tmp_order_agg"

        dqs = generate_dq_sql(ts)
        assert len(dqs) == 0, f"tmp 中间表不应生成 DQ，实际: {list(dqs.keys())}"

    def test_view_step_does_not_generate_dq(self):
        """视图步骤（is_view_step=True）不生成 DQ"""
        rules = {
            "R0001": {
                "rule_name": "视图步骤", "scenario": "default", "exec_sequence": 1,
                "target_table": "dwb_test_i", "is_view_step": True,
                "design_intent": "镜像视图", "source_tables": [],
                "fields": [], "field_count": 0,
            }
        }
        ts = make_ts_json(table="dwb_test_i", rules=rules)

        dqs = generate_dq_sql(ts)
        assert len(dqs) == 0, f"视图步骤不应生成 DQ，实际: {list(dqs.keys())}"
