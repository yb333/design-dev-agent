"""类型转换风险检测测试。

覆盖：
- type_compat.assess_type_risk 单测（各种类型组合）
- precheck._check_type_risk 流程（检测/骨架生成/决策校验/阻断/放行）
"""

import sys
from pathlib import Path

# 把 scripts 目录加进 sys.path（conftest 已加，这里确保 type_compat 可 import）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "dws-design" / "scripts"))

from type_compat import assess_type_risk, RISK_LABEL_CN
from precheck import (
    precheck, _detect_type_risks, _generate_type_risk_skeleton,
    _validate_type_risk_decision, PrecheckResult,
)
from conftest import make_type_risk_rs_input


# ============================================================
# assess_type_risk 单测
# ============================================================
class TestAssessTypeRisk:
    def test_same_type_no_risk(self):
        assert assess_type_risk("varchar(50)", "varchar(50)") is None
        assert assess_type_risk("int", "int") is None

    def test_compatible_no_risk(self):
        # 目标更宽容容
        assert assess_type_risk("varchar(10)", "varchar(20)") is None
        # 整数家族互转
        assert assess_type_risk("int", "bigint") is None
        assert assess_type_risk("smallint", "integer") is None
        # PG 内部名 int8/int4 和 SQL 标准名 bigint/integer 等价，互通无风险
        assert assess_type_risk("int8(64)", "bigint") is None
        assert assess_type_risk("int4", "integer") is None
        assert assess_type_risk("int8", "int4") is None
        # 整数→数值 安全跨类
        assert assess_type_risk("bigint", "numeric(20,2)") is None

    def test_int_cross_category_incompatible(self):
        """整数→varchar 是安全方向（长度兜底）；→date 仍报不兼容。"""
        assert assess_type_risk("int8", "varchar(20)") is None  # bigint 20 字符恰装下
        assert assess_type_risk("int4", "date") == "type_incompatible"

    def test_length_overflow(self):
        assert assess_type_risk("varchar(200)", "varchar(50)") == "length_overflow"
        assert assess_type_risk("varchar(100)", "varchar(60)") == "length_overflow"

    def test_precision_loss(self):
        assert assess_type_risk("numeric(12,2)", "numeric(10,2)") == "precision_loss"
        # 标度收窄也是精度问题
        assert assess_type_risk("numeric(10,4)", "numeric(10,2)") == "precision_loss"

    def test_source_unlimited_target_limited_reports_risk(self):
        """source 无参（值可能任意大）+ target 有限制 → 报风险（designer 需加兜底）。

        这是 type_compat 的修正点：之前 source 无参误判"兼容"放行，
        现在正确判"有风险"——source 值可能超 target，必须报出来让 designer 加 CAST/截取。
        """
        # numeric 无参 → numeric(18,2)：值可能超 18 位，precision_loss
        assert assess_type_risk("numeric", "numeric(18,2)") == "precision_loss"
        # text → varchar(100)：值可能超 100 字符，length_overflow
        assert assess_type_risk("text", "varchar(100)") == "length_overflow"

    def test_target_unlimited_no_risk(self):
        """target 无限制（numeric 无参/text）能容纳任何 source → 无风险。"""
        assert assess_type_risk("numeric(38,10)", "numeric") is None
        assert assess_type_risk("varchar(100)", "text") is None
        # 都无限制
        assert assess_type_risk("numeric", "numeric") is None

    def test_type_incompatible(self):
        assert assess_type_risk("varchar(20)", "date") == "type_incompatible"
        assert assess_type_risk("int", "date") == "type_incompatible"
        assert assess_type_risk("boolean", "int") == "type_incompatible"

    def test_empty_type_no_risk(self):
        assert assess_type_risk("", "varchar(50)") is None
        assert assess_type_risk("varchar(50)", "") is None


class TestCharsetSemantics:
    """字符类型互跨（nvarchar↔varchar 等）：长度口径（字节/字符）取决于集群兼容模式，
    同长度也可能装不下中文——不自动判兼容，报 charset_semantics 走人工决策。
    两个方向都报（哪个方向装不下脚本不猜）。
    """

    def test_n_to_non_n_same_length_is_risk(self):
        """N 系 → 非 N 系同长度：中文 UTF-8 3字节/字，字节口径目标装不下。"""
        assert assess_type_risk("nvarchar(4000)", "varchar(4000)") == "charset_semantics"
        assert assess_type_risk("nvarchar2(4000)", "varchar(4000)") == "charset_semantics"
        assert assess_type_risk("nvarchar2(4000)", "varchar2(4000)") == "charset_semantics"

    def test_reverse_direction_also_risk(self):
        """非N→N 等长安全（字符数≤字节数）；N→非N 同长度仍报（口径取决于集群，人决策）。"""
        assert assess_type_risk("varchar(4000)", "nvarchar(4000)") is None
        assert assess_type_risk("varchar2(4000)", "nvarchar2(4000)") is None
        assert assess_type_risk("nvarchar2(4000)", "varchar(4000)") == "charset_semantics"

    def test_varchar_vs_varchar2_is_risk(self):
        """varchar↔varchar2：字节/字符口径经典差异对。"""
        assert assess_type_risk("varchar2(4000)", "varchar(4000)") == "charset_semantics"
        assert assess_type_risk("varchar(4000)", "varchar2(4000)") == "charset_semantics"

    def test_same_base_keeps_length_logic(self):
        """同 base 不涉口径问题，维持长度比较。"""
        assert assess_type_risk("nvarchar2(50)", "nvarchar2(100)") is None
        assert assess_type_risk("nvarchar2(200)", "nvarchar2(50)") == "length_overflow"
        assert assess_type_risk("varchar2(50)", "varchar2(100)") is None
        assert assess_type_risk("varchar2(200)", "varchar2(50)") == "length_overflow"

    def test_target_unlimited_safe(self):
        """目标 text 无长度限制，任何口径都装得下 → 无风险。"""
        assert assess_type_risk("nvarchar2(4000)", "text") is None

    def test_is_type_compatible_not_auto_pass(self):
        from type_compat import is_type_compatible
        assert is_type_compatible("nvarchar2(4000)", "varchar(4000)") is False
        assert is_type_compatible("nvarchar2(50)", "nvarchar2(100)") is True

    def test_label_registered(self):
        assert "charset_semantics" in RISK_LABEL_CN

    def test_risk_label_cn(self):
        assert RISK_LABEL_CN["length_overflow"] == "长度超长"
        assert RISK_LABEL_CN["precision_loss"] == "精度收窄"
        assert RISK_LABEL_CN["type_incompatible"] == "跨大类不兼容"


# ============================================================
# _detect_type_risks 测试
# ============================================================
class TestDetectTypeRisks:
    def test_only_direct_fields_checked(self):
        """加工类字段不检测。"""
        from conftest import make_rs_input
        rs = make_rs_input(fields=[
            {"source_table": "ods_f", "source_column": "a", "source_type": "varchar(200)",
             "transform_rule": "数据加工", "transform_detail": "处理", "target_column": "a",
             "target_column_cn": "a", "target_type": "varchar(50)", "source_alias": "t", "remark": ""},
        ], has_audit=False)
        batch, individual = _detect_type_risks(rs)
        assert batch == [] and individual == []

    def test_batch_vs_individual_split(self):
        """常规风险进 batch、跨大类进 individual。"""
        rs = make_type_risk_rs_input([
            {"target_column": "remark", "source_type": "varchar(200)", "target_type": "varchar(50)"},
            {"target_column": "biz_date", "source_type": "varchar(20)", "target_type": "date"},
        ])
        batch, individual = _detect_type_risks(rs)
        assert len(batch) == 1 and batch[0]["target_column"] == "remark"
        assert len(individual) == 1 and individual[0]["target_column"] == "biz_date"

    def test_no_risk_returns_empty(self):
        """无风险字段返回空。"""
        from conftest import make_rs_input
        rs = make_rs_input(has_audit=False)
        batch, individual = _detect_type_risks(rs)
        assert batch == [] and individual == []

    def test_missing_type_skipped(self):
        """缺 source_type/target_type 的字段跳过。"""
        from conftest import make_rs_input
        rs = make_rs_input(fields=[
            {"source_table": "ods_f", "source_column": "a", "source_type": "",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "a", "target_type": "varchar(50)",
             "source_alias": "t", "remark": ""},
        ], has_audit=False)
        batch, individual = _detect_type_risks(rs)
        assert batch == [] and individual == []


# ============================================================
# _check_type_risk 流程测试（骨架生成/阻断/放行）
# ============================================================
class TestCheckTypeRiskFlow:
    def test_no_risk_no_block(self, tmp_path):
        """无风险字段 → 不生成决策文件、不阻断。"""
        from conftest import make_rs_input
        rs = make_rs_input(has_audit=False)
        decision_path = tmp_path / "type_risk_decision.yaml"
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert not result.errors
        assert not decision_path.exists()

    def test_risk_generates_skeleton_and_blocks(self, tmp_path, capsys):
        """有风险无决策 → 生成骨架 + 阻断 + stdout TYPE_RISK_PENDING。"""
        rs = make_type_risk_rs_input()
        decision_path = tmp_path / "type_risk_decision.yaml"
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert result.errors  # 阻断
        assert decision_path.exists()  # 骨架已生成
        captured = capsys.readouterr()
        assert "TYPE_RISK_PENDING" in captured.out  # stdout 摘要

    def test_filled_decision_passes(self, tmp_path):
        """决策填全 → 放行。"""
        rs = make_type_risk_rs_input()
        decision_path = tmp_path / "type_risk_decision.yaml"
        # 先生成骨架
        _generate_type_risk_skeleton(decision_path, *_detect_type_risks(rs))
        # 填全决策
        import yaml
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
        dec["批量处置策略"] = "加安全处理"
        for item in dec.get("跨大类风险字段", []):
            item["处置"] = "转换"
        decision_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        # 重跑检测
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert not result.errors  # 放行

    def test_partial_decision_blocks(self, tmp_path):
        """决策没填全 → 阻断。"""
        rs = make_type_risk_rs_input()
        decision_path = tmp_path / "type_risk_decision.yaml"
        _generate_type_risk_skeleton(decision_path, *_detect_type_risks(rs))
        # 只填批量，不填跨大类
        import yaml
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
        dec["批量处置策略"] = "加安全处理"
        decision_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert result.errors  # 跨大类没填全，阻断

    def test_return_source_requires_reason(self, tmp_path):
        """选'返源端'但没填原因 → 阻断。"""
        rs = make_type_risk_rs_input([
            {"target_column": "biz_date", "source_type": "varchar(20)", "target_type": "date"},
        ])
        decision_path = tmp_path / "type_risk_decision.yaml"
        _generate_type_risk_skeleton(decision_path, *_detect_type_risks(rs))
        import yaml
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
        dec["批量处置策略"] = "加安全处理"  # 没 batch 字段也无妨
        for item in dec.get("跨大类风险字段", []):
            item["处置"] = "返源端"
            item["原因"] = ""  # 没填原因
        decision_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert result.errors  # 没填原因阻断

    def test_stale_decision_regenerates(self, tmp_path):
        """mapping 改了字段、决策文件过期 → 重新生成骨架阻断。"""
        rs = make_type_risk_rs_input()
        decision_path = tmp_path / "type_risk_decision.yaml"
        _generate_type_risk_skeleton(decision_path, *_detect_type_risks(rs))
        import yaml
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
        dec["批量处置策略"] = "加安全处理"
        dec["跨大类风险字段"][0]["处置"] = "转换"
        decision_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        # 现在 mapping 变了（多一个风险字段），决策文件不再匹配
        rs["field_mappings"].append({
            "source_table": "ods_test_f", "source_column": "new_field",
            "source_type": "varchar(300)", "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "new_field", "target_column_cn": "new_field", "target_type": "varchar(50)",
            "source_alias": "t", "remark": "",
        })
        result = PrecheckResult()
        _check_type_risk_inner(rs, result, decision_path)
        assert result.errors  # 字段不一致，重新生成阻断


def _check_type_risk_inner(rs_input, result, decision_path):
    """直接调 _check_type_risk（绕过 precheck 的短路，专测类型风险逻辑）。"""
    from precheck import _check_type_risk
    _check_type_risk(rs_input, result, decision_path)


# ============================================================
# 方向性：数值→字符是安全方向（不逐字段问人），字符→数值仍危险
# ============================================================

class TestDirectionalNumberToText:

    def test_number_to_text_widening_pass(self):
        """数值→字符且长度够 = 无风险（直接处理，不问人）"""
        from type_compat import assess_type_risk
        assert assess_type_risk("numeric(18,2)", "varchar(50)") is None
        assert assess_type_risk("bigint", "varchar(50)") is None
        assert assess_type_risk("integer", "text") is None

    def test_number_to_text_tight_is_batch_risk(self):
        """数值→字符长度紧 = 降级常规档（批量），不进跨大类逐字段档"""
        from type_compat import assess_type_risk
        assert assess_type_risk("numeric(18,2)", "varchar(10)") == "length_overflow"
        assert assess_type_risk("bigint", "varchar(15)") == "length_overflow"
        assert assess_type_risk("numeric", "varchar(50)") == "length_overflow"

    def test_text_to_number_still_dangerous(self):
        """字符→数值（真危险方向）仍是跨大类逐字段档"""
        from type_compat import assess_type_risk
        assert assess_type_risk("varchar(32)", "numeric(18,2)") == "type_incompatible"
        assert assess_type_risk("varchar(32)", "bigint") == "type_incompatible"

    def test_char_family_cases_unchanged(self):
        """同字符扩长=放行；nvarchar 口径互跨=仍问人（回归守护）"""
        from type_compat import assess_type_risk
        assert assess_type_risk("varchar(30)", "varchar(50)") is None
        assert assess_type_risk("nvarchar(30)", "varchar(50)") == "charset_semantics"


class TestDirectionalCharsetAndDatetime:

    def test_varchar_to_nvarchar_no_shrink_pass(self):
        """varchar→nvarchar 不缩长度 = 安全（字符数 ≤ 字节数，必装下）"""
        from type_compat import assess_type_risk
        assert assess_type_risk("varchar(30)", "nvarchar(30)") is None
        assert assess_type_risk("varchar(30)", "nvarchar(50)") is None

    def test_varchar_to_nvarchar_shrink_is_batch(self):
        """varchar→nvarchar 缩长度 = 常规档（安全方向只剩长度问题）"""
        from type_compat import assess_type_risk
        assert assess_type_risk("varchar(30)", "nvarchar(20)") == "length_overflow"

    def test_n_to_non_n_still_asks(self):
        """N系→非N系（字符→字节）仍人决策（回归守护）"""
        from type_compat import assess_type_risk
        assert assess_type_risk("nvarchar(30)", "varchar(50)") == "charset_semantics"
        assert assess_type_risk("varchar(30)", "varchar2(64)") == "charset_semantics"

    def test_datetime_to_text_pass_and_batch(self):
        """日期时间→字符：长度够放行；不够归常规档；反方向仍跨大类"""
        from type_compat import assess_type_risk
        assert assess_type_risk("date", "varchar(32)") is None
        assert assess_type_risk("timestamp(6)", "varchar(32)") is None
        assert assess_type_risk("timestamp(6)", "varchar(20)") == "length_overflow"
        assert assess_type_risk("varchar(32)", "timestamp(0)") == "type_incompatible"
