"""pick_dq_context（dws-dq-producer 输入切片）测试——2026-09-14 DQ 拆分。

覆盖三件套：确定性闭包展开（跨字段传递依赖）/ 存疑显式标记（人话逻辑）/
按需查询服务（--query/--field 深挖）+ 切片结构（RS 原文/目标/业务键）。
"""

import sys

sys.path.insert(0, "skills/new-pipe/scripts")

from pick_dq_context import build_context, query_mapping, query_field  # noqa: E402


def _fm(target, source="", rule="直取", detail="", cn="", src_table="ods_test_f", alias="s"):
    return {"target_column": target, "target_column_cn": cn or target,
            "target_type": "varchar(50)",
            "transform_rule": rule, "transform_detail": detail,
            "source_table": src_table, "source_column": source, "source_alias": alias}


def _rs(fms, dq_needs=None):
    return {
        "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f"}}},
        "source_tables": [{"source_schema": "ods", "source_table": "ods_test_f", "source_alias": "s"}],
        "field_mappings": fms,
        "dq_requirements": dq_needs if dq_needs is not None else [
            {"scope": "字段级", "check_type": "一致性检查", "rule_name": "金额口径复核",
             "rule_desc": "比对 order_amount 与源表 pay+discount 独立重算值"}],
    }


def _ts():
    return {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试"}}},
            "design": {"business_key": ["order_id"]},
            "tables": {"dwb_test_f": {"fields": [{"name": "order_amount"}]}}}


class TestClosure:
    def test_seed_from_rs_text(self):
        """RS 需求文本提到的目标字段进种子（词边界：order_amount 命中，order_amt 不命中）。"""
        fms = [_fm("order_id"), _fm("order_amount", source="pay", detail="s.pay + s.discount"),
               _fm("order_amt", source="amt")]
        ctx = build_context(_rs(fms), _ts())
        assert "order_amount" in ctx["closure"]["seed_fields"]
        assert "order_amt" not in ctx["closure"]["seed_fields"]

    def test_closure_expands_transitive_dependency(self):
        """跨字段传递依赖：amount ← tax（tax 是目标列）→ tax 的行进闭包。"""
        fms = [
            _fm("order_id", source="id"),
            _fm("amount", rule="加工", detail="s.pay + tax", source="pay"),   # 引用目标列 tax
            _fm("tax", rule="加工", detail="s.tax_rate * s.base", source="tax_rate"),
        ]
        rs = _rs(fms, dq_needs=[{"check_type": "一致性", "rule_name": "x", "rule_desc": "比对 amount"}])
        ctx = build_context(rs, _ts())
        targets = {e["target_column"] for e in ctx["closure"]["entries"]}
        assert {"amount", "tax"} <= targets  # tax 随闭包展开进 entries

    def test_word_boundary_not_substring(self):
        """order_id 不因子串误命中 order_id_ext（词边界匹配）。"""
        fms = [_fm("order_id", source="id"), _fm("order_id_ext", source="ext")]
        rs = _rs(fms, dq_needs=[{"check_type": "x", "rule_name": "y", "rule_desc": "查 order_id"}])
        ctx = build_context(rs, _ts())
        assert "order_id" in ctx["closure"]["seed_fields"]
        assert "order_id_ext" not in ctx["closure"]["seed_fields"]

    def test_direct_rows_not_suspect(self):
        fms = [_fm("order_id", source="id")]
        ctx = build_context(_rs(fms), _ts())
        assert ctx["closure"]["suspect"] == []


class TestSuspect:
    def test_human_logic_marked_suspect(self):
        """人话逻辑（无可解析引用）显式标记进 suspect——不是静默缺失。"""
        fms = [_fm("order_amount", rule="加工", detail="按订单状态折算金额", source="status")]
        ctx = build_context(_rs(fms), _ts())
        assert len(ctx["closure"]["suspect"]) == 1
        assert ctx["closure"]["suspect"][0]["target_column"] == "order_amount"
        assert "人话" in ctx["closure"]["suspect"][0]["reason"]

    def test_empty_detail_marked_suspect(self):
        fms = [_fm("order_amount", rule="加工", detail="", source="")]
        ctx = build_context(_rs(fms), _ts())
        assert any("为空" in s["reason"] for s in ctx["closure"]["suspect"])


class TestContextShape:
    def test_context_structure(self):
        fms = [_fm("order_amount", source="pay", detail="s.pay")]
        ctx = build_context(_rs(fms), _ts())
        assert ctx["dq_requirements"][0]["rule_name"] == "金额口径复核"
        assert ctx["target"]["f_table"] == "dws.dwb_test_f"
        assert ctx["target"]["business_key"] == ["order_id"]
        assert ctx["source_tables"][0]["table"] == "ods_test_f"
        # 目标字段全量清单（不只闭包内——DQ 可检查任何目标字段）
        assert any(f["target_column"] == "order_amount" for f in ctx["target"]["fields"])
        assert "服务说明" in ctx and "--query" in ctx["服务说明"]["深挖检索"]


class TestQueryService:
    def test_query_keyword_hits(self):
        fms = [_fm("order_amount", source="pay", detail="s.pay + s.discount"),
               _fm("order_id", source="id")]
        rs = _rs(fms)
        hits = query_mapping(rs, "discount")
        assert len(hits) == 1 and hits[0]["target_column"] == "order_amount"

    def test_query_field_both_sides(self):
        """--field 查字段名：作为目标列命中 + 作为源列命中（producer 深挖两侧）。"""
        fms = [
            _fm("amount", source="pay"),
            _fm("tax", rule="加工", detail="s.pay * 0.1", source="pay"),  # pay 作为源列
        ]
        rs = _rs(fms)
        hits = query_field(rs, "pay")
        assert {h["target_column"] for h in hits} == {"amount", "tax"}
