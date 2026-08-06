"""gate_summary.py 测试：generate_gate1_summary。

闸口①摘要从 ts.json 直接生成（不需要 AI），全是固定字段投影。
测纯函数行为（摘要内容、字段统计、关联安全、主键调整），不连库不读真实文件。
"""

import pytest

from gate_summary import generate_gate1_summary


def _minimal_ts(**overrides):
    """构造最小 ts.json（generate_gate1_summary 的输入）。"""
    ts = {
        "meta": {
            "target": {
                "f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试宽表"},
            },
            "field_count": {"business": 10, "audit": 4, "total": 14},
        },
        "design": {},
        "rules": {},
    }
    ts.update(overrides)
    return ts


class TestGenerateGate1SummaryBasics:
    def test_header_present(self):
        out = generate_gate1_summary(_minimal_ts())
        assert "## 设计完成，请确认方向" in out

    def test_target_table_displayed(self):
        out = generate_gate1_summary(_minimal_ts())
        assert "dws.dwb_test_f" in out
        assert "测试宽表" in out

    def test_rule_and_scene_count(self):
        ts = _minimal_ts(rules={
            "R0001": {"rule_name": "规则1", "scenario": "default", "target_table": "dwb_test_f"},
            "R0002": {"rule_name": "规则2", "scenario": "vip", "target_table": "dwb_test_f"},
        })
        out = generate_gate1_summary(ts)
        assert "规则数**: 2" in out
        # 场景数：default 通常被过滤（只数有值且非空的），vip 算 1 个
        assert "场景数" in out

    def test_field_statistics(self):
        out = generate_gate1_summary(_minimal_ts())
        assert "业务 10" in out
        assert "审计 4" in out
        assert "总计 14" in out

    def test_choice_options_present(self):
        out = generate_gate1_summary(_minimal_ts())
        assert "确认设计" in out
        assert "放弃" in out


class TestGate1RuleOverview:
    def test_rule_overview_table(self):
        ts = _minimal_ts(rules={
            "R0001": {"rule_name": "汇总", "target_table": "dwb_test_f",
                      "field_count": 5, "design_intent": "按用户聚合"},
        })
        out = generate_gate1_summary(ts)
        assert "| R0001 |" in out
        assert "汇总" in out
        assert "按用户聚合" in out

    def test_long_intent_truncated(self):
        """设计意图超 60 字截断。"""
        long_intent = "按" + "用户" * 40 + "聚合，产出汇总表"  # 远超 60 字
        assert len(long_intent) > 60
        ts = _minimal_ts(rules={
            "R0001": {"rule_name": "r", "target_table": "t",
                      "field_count": 1, "design_intent": long_intent},
        })
        out = generate_gate1_summary(ts)
        # 规则概览表里应出现截断标记
        rule_line = [ln for ln in out.splitlines() if "R0001" in ln][0]
        assert "..." in rule_line


class TestGate1JoinSafety:
    def test_risky_join_shown(self):
        """join_key_unique=false 的关联风险被展示。"""
        ts = _minimal_ts(rules={
            "R0001": {"rule_name": "r", "target_table": "t", "join_safety": [
                {"table": "dim_store", "join_key_unique": False,
                 "strategy": "GROUP BY 收敛", "reason": "存在重复"},
            ]},
        })
        out = generate_gate1_summary(ts)
        assert "dim_store" in out
        assert "GROUP BY 收敛" in out

    def test_safe_join_no_risk_section(self):
        """所有关联键唯一 -> 显示'无需特殊对齐策略'。"""
        ts = _minimal_ts(rules={
            "R0001": {"rule_name": "r", "target_table": "t", "join_safety": [
                {"table": "dim_store", "join_key_unique": True},
            ]},
        })
        out = generate_gate1_summary(ts)
        assert "无需特殊对齐策略" in out


class TestGate1BusinessKeyAdjustment:
    def test_adjusted_key_shown(self):
        """主键调整过的（business_key_design.adjusted=true）展示调整说明。"""
        ts = _minimal_ts(design={
            "business_key": ["user_id", "dt"],
            "business_key_design": {
                "adjusted": True,
                "input_key": ["user_id"],
                "reason": "粒度变化需加 dt",
            },
        })
        out = generate_gate1_summary(ts)
        assert "主键已调整" in out
        assert "user_id" in out
        assert "dt" in out

    def test_unadjusted_key_not_flagged(self):
        """主键未调整 -> 不出'主键已调整'。"""
        ts = _minimal_ts(design={
            "business_key": ["user_id"],
            "business_key_design": {"adjusted": False},
        })
        out = generate_gate1_summary(ts)
        assert "主键已调整" not in out


class TestGate1AuditFields:
    def test_supplemented_audit_listed(self):
        """有自动补充的审计字段 -> 列出来。"""
        ts = _minimal_ts(design={"audit_supplemented": ["del_flag", "crt_cycle_id"]})
        out = generate_gate1_summary(ts)
        assert "del_flag" in out
        assert "crt_cycle_id" in out
        assert "自动补充" in out

    def test_all_from_source(self):
        """无补充 -> 显示'全部来自 RS/mapping'。"""
        ts = _minimal_ts(design={"audit_supplemented": []})
        out = generate_gate1_summary(ts)
        assert "全部来自 RS/mapping" in out


class TestGate1Segmentation:
    def test_segmentation_shown(self):
        """分段决策展示。"""
        ts = _minimal_ts(design={
            "complexity_analysis": {
                "segmentation_decision": "分段",
                "segmentation_reason": "JOIN 多、中间表复用",
            },
        })
        out = generate_gate1_summary(ts)
        assert "分段决策" in out
        assert "分段" in out
