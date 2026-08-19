"""sql_fence 测试：AST 级 SQL 围栏（docs/specs/opt/05 §二）。

判定重点：老列逐列结构等价（格式差异消解、等价改写=越界）、仅追加声明列、
JOIN/WHERE/GROUP BY 冻结、不支持的形态显式转人工。
"""
import pytest

from sql_fence import check_sql_fence, rule_declaration

B_R2 = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount "
        "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")

DECL_DIRECT = {"rule": "R0002", "fields": ["pay_channel"], "new_joins": []}
DECL_JOIN = {"rule": "R0002", "fields": ["channel_name"],
             "new_joins": [{"rule": "R0002", "table": "dim_channel", "alias": "c",
                            "on": "t.order_id = c.order_id"}]}


def msgs(violations, typ=None):
    return [x["message"] for x in violations if typ is None or x["type"] == typ]


class TestPass:
    def test_format_only_rewrite_passes(self):
        """格式/空白差异必须消解（双方各自归一生成）。无字段声明的纯格式重写。"""
        new = ("SELECT\n  t.order_id,\n  t.cust_id,\n  SUM(t.amount) AS total_amount\n"
               "FROM dws.tmp_trade_order t\nGROUP BY t.order_id, t.cust_id")
        assert check_sql_fence(B_R2, new, {"rule": "R0002", "fields": [], "new_joins": []}) == []

    def test_declared_column_appended(self):
        new = (B_R2[:-1] + ", t.pay_channel FROM dws.tmp_trade_order t "
               "GROUP BY t.order_id, t.cust_id").replace(
               "SELECT t.order_id, t.cust_id", "SELECT t.order_id, t.cust_id")
        # 更直观的构造：完整重写
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, a.pay_channel "
               "FROM dws.tmp_trade_order t LEFT JOIN ods.ods_trade_order_di a "
               "ON t.order_id = a.order_id GROUP BY t.order_id, t.cust_id")
        # ↑ 这里动了 JOIN，direct 声明下应违规——改用真 direct 场景：
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, t.pay_channel "
               "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")
        assert check_sql_fence(B_R2, new, DECL_DIRECT) == []

    def test_declared_join_and_column(self):
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, c.channel_name "
               "FROM dws.tmp_trade_order t LEFT JOIN dws.dim_channel c "
               "ON t.order_id = c.order_id GROUP BY t.order_id, t.cust_id")
        assert check_sql_fence(B_R2, new, DECL_JOIN) == []


class TestOverreach:
    def test_undeclared_extra_column(self):
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, t.remark "
               "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("remark" in m for m in msgs(vs, "overreach"))

    def test_old_column_expr_modified(self):
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount + 1) AS total_amount "
               "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id")
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("total_amount" in m and "被修改" in m for m in msgs(vs, "overreach"))

    def test_semantic_equivalent_rewrite_blocked(self):
        """笨标准：='N' 改 <>'Y' 语义等价也拦。"""
        b = "SELECT a.order_id FROM ods.t a WHERE a.del='N'"
        n = "SELECT a.order_id FROM ods.t a WHERE a.del<>'Y'"
        vs = check_sql_fence(b, n, {"rule": "R1", "fields": [], "new_joins": []})
        assert any("WHERE" in m for m in msgs(vs, "overreach"))

    def test_old_column_dropped(self):
        new = ("SELECT t.order_id, SUM(t.amount) AS total_amount "
               "FROM dws.tmp_trade_order t GROUP BY t.order_id")
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("cust_id" in m and "丢失" in m for m in msgs(vs, "overreach"))

    def test_undeclared_join(self):
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, x.flag "
               "FROM dws.tmp_trade_order t LEFT JOIN dws.dim_x x ON t.order_id = x.id "
               "GROUP BY t.order_id, t.cust_id")
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("dim_x" in m or "JOIN" in m for m in msgs(vs, "overreach"))

    def test_declared_join_wrong_table_same_alias(self):
        """声明的别名挂了别的表——不算已声明 JOIN。"""
        bad_decl = {"rule": "R0002", "fields": ["channel_name"],
                    "new_joins": [{"rule": "R0002", "table": "dim_other", "alias": "c"}]}
        new = ("SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, c.channel_name "
               "FROM dws.tmp_trade_order t LEFT JOIN dws.dim_channel c "
               "ON t.order_id = c.order_id GROUP BY t.order_id, t.cust_id")
        vs = check_sql_fence(B_R2, new, bad_decl)
        assert any("JOIN" in m for m in msgs(vs, "overreach"))

    def test_group_by_changed(self):
        new = ("SELECT t.order_id, SUM(t.amount) AS total_amount "
               "FROM dws.tmp_trade_order t GROUP BY t.order_id")
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("GROUP BY" in m for m in msgs(vs, "overreach"))


class TestMissing:
    def test_declared_field_absent(self):
        new = B_R2  # 忘了加声明字段
        vs = check_sql_fence(B_R2, new, DECL_DIRECT)
        assert any("pay_channel" in m and "未出现" in m for m in msgs(vs, "missing"))


class TestUnsupported:
    def test_union_top_level(self):
        b = "SELECT a FROM t1 UNION ALL SELECT a FROM t2"
        vs = check_sql_fence(b, b, {"rule": "R", "fields": [], "new_joins": []})
        assert any("人工审查" in m for m in msgs(vs))

    def test_select_star(self):
        b = "SELECT * FROM t"
        vs = check_sql_fence(b, b + " WHERE 1=1", {"rule": "R", "fields": [], "new_joins": []})
        assert any("SELECT \\*" in m or "SELECT *" in m for m in msgs(vs))


class TestRuleDeclaration:
    def test_derive_from_change(self):
        change = {"change_type": "add_field", "fields": [
            {"field": "channel_name", "target_table": "dwb", "placed_rules": ["R0001", "R0002"],
             "new_joins": [{"rule": "R0001", "table": "dim_channel", "alias": "c"}]}]}
        d1 = rule_declaration(change, "R0001")
        assert d1["fields"] == ["channel_name"] and len(d1["new_joins"]) == 1
        d2 = rule_declaration(change, "R0002")
        assert d2["fields"] == ["channel_name"] and d2["new_joins"] == []
        d3 = rule_declaration(change, "R0009")
        assert d3 == {"rule": "R0009", "fields": [], "new_joins": []}
