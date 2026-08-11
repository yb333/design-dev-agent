"""
类型风险决策填值器 (fill_type_risk_decision.py) 测试。

脚本读 precheck 生成的骨架，填用户的决策值，替代 agent 手写 yaml。
"""

import pytest
import sys
from pathlib import Path

DESIGN_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-design" / "scripts"
sys.path.insert(0, str(DESIGN_REFS))


@pytest.fixture
def skeleton_file(tmp_path):
    """造一个 precheck 风格的骨架文件。"""
    from precheck import _generate_type_risk_skeleton
    dec = tmp_path / "type_risk_decision.yaml"
    batch = [
        {"target_column": "remark", "source_type": "varchar(200)",
         "target_type": "varchar(50)", "risk_cn": "长度超长"},
        {"target_column": "user_remark", "source_type": "varchar(300)",
         "target_type": "varchar(50)", "risk_cn": "长度超长"},
    ]
    individual = [
        {"target_column": "biz_date", "source_type": "varchar(20)",
         "target_type": "date", "risk_cn": "跨大类不兼容"},
        {"target_column": "amount_str", "source_type": "varchar(20)",
         "target_type": "decimal(18,2)", "risk_cn": "跨大类不兼容"},
    ]
    _generate_type_risk_skeleton(dec, batch, individual)
    return dec


class TestParseKvList:
    def test_basic(self):
        from fill_type_risk_decision import parse_kv_list
        assert parse_kv_list("a:1,b:2") == {"a": "1", "b": "2"}

    def test_empty(self):
        from fill_type_risk_decision import parse_kv_list
        assert parse_kv_list("") == {}
        assert parse_kv_list("   ") == {}

    def test_strips_whitespace(self):
        from fill_type_risk_decision import parse_kv_list
        assert parse_kv_list(" a : 1 , b : 2 ") == {"a": "1", "b": "2"}

    def test_value_with_colon(self):
        """值里含冒号，只按第一个冒号分割"""
        from fill_type_risk_decision import parse_kv_list
        assert parse_kv_list("reason:原因:详情") == {"reason": "原因:详情"}

    def test_no_colon_raises(self):
        from fill_type_risk_decision import parse_kv_list
        with pytest.raises(ValueError, match="格式错误"):
            parse_kv_list("nopair")


class TestFillDecision:
    def test_fill_batch_strategy(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        import yaml
        result = fill_decision(skeleton_file, batch_strategy="加安全处理")
        dec = yaml.safe_load(result)
        assert dec["批量处置策略"] == "加安全处理"

    def test_fill_field_decisions(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        import yaml
        result = fill_decision(
            skeleton_file,
            field_decisions={"biz_date": "转换", "amount_str": "不加"},
        )
        dec = yaml.safe_load(result)
        ind = {item["目标字段"]: item for item in dec["跨大类风险字段"]}
        assert ind["biz_date"]["处置"] == "转换"
        assert ind["amount_str"]["处置"] == "不加"

    def test_return_to_source_requires_reason(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        result = fill_decision(
            skeleton_file,
            field_decisions={"biz_date": "返源端"},
            reasons={"biz_date": "源端建议改 date"},
        )
        import yaml
        dec = yaml.safe_load(result)
        ind = {item["目标字段"]: item for item in dec["跨大类风险字段"]}
        assert ind["biz_date"]["处置"] == "返源端"
        assert ind["biz_date"]["原因"] == "源端建议改 date"

    def test_field_list_unchanged(self, skeleton_file):
        """填值不改变字段清单（防 agent 传错导致清单漂移）"""
        from fill_type_risk_decision import fill_decision
        import yaml
        original = yaml.safe_load(skeleton_file.read_text())
        result = fill_decision(
            skeleton_file, batch_strategy="加安全处理",
            field_decisions={"biz_date": "转换"},
        )
        filled = yaml.safe_load(result)
        # 字段清单不变
        orig_batch = {i["目标字段"] for i in original["常规风险字段"]}
        filled_batch = {i["目标字段"] for i in filled["常规风险字段"]}
        assert orig_batch == filled_batch
        orig_ind = {i["目标字段"] for i in original["跨大类风险字段"]}
        filled_ind = {i["目标字段"] for i in filled["跨大类风险字段"]}
        assert orig_ind == filled_ind


class TestFillDecisionValidation:
    def test_invalid_batch_strategy(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        with pytest.raises(ValueError, match="批量处置策略.*不合法"):
            fill_decision(skeleton_file, batch_strategy="加处理")

    def test_invalid_field_decision(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        with pytest.raises(ValueError, match="处置.*不合法"):
            fill_decision(skeleton_file, field_decisions={"biz_date": "转"})

    def test_unknown_field_raises(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        with pytest.raises(ValueError, match="不在决策清单"):
            fill_decision(skeleton_file, field_decisions={"unknown_col": "转换"})

    def test_return_without_reason_raises(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        with pytest.raises(ValueError, match="返源端.*没传.*reasons"):
            fill_decision(skeleton_file, field_decisions={"biz_date": "返源端"})

    def test_nonexistent_file(self, tmp_path):
        from fill_type_risk_decision import fill_decision
        with pytest.raises(ValueError, match="不存在"):
            fill_decision(tmp_path / "no.yaml", batch_strategy="加安全处理")


class TestEndToEnd:
    """填值后的文件能被 precheck 的 _validate_type_risk_decision 接受。"""

    def test_filled_passes_precheck_validation(self, skeleton_file):
        from fill_type_risk_decision import fill_decision
        from precheck import _validate_type_risk_decision, PrecheckResult
        import yaml

        # 先填值
        filled = fill_decision(
            skeleton_file,
            batch_strategy="加安全处理",
            field_decisions={"biz_date": "转换", "amount_str": "返源端"},
            reasons={"amount_str": "源端建议改类型"},
        )
        skeleton_file.write_text(filled, encoding="utf-8")

        # 用 precheck 的验证函数校验
        batch = [
            {"target_column": "remark"},
            {"target_column": "user_remark"},
        ]
        individual = [
            {"target_column": "biz_date"},
            {"target_column": "amount_str"},
        ]
        result = PrecheckResult()
        ok = _validate_type_risk_decision(skeleton_file, batch, individual, result)
        assert ok, f"precheck 验证失败: {result.errors}"
