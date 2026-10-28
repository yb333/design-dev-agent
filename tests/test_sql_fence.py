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
        assert d3 == {"rule": "R0009", "fields": [], "new_joins": [], "modify_types": {}, "modify_logics": set()}


class TestCastWrap:
    """场景 B（类型修改）：类型修改列允许 cast(老表达式 AS 新类型) 包裹——
    AST 判定内层归一==baseline 原文+目标类型匹配；cast 之外的一切改写照拦。"""

    BASE = "SELECT a.x AS x, a.y AS y FROM ods.t a"
    DECL = {"rule": "R1", "fields": [], "new_joins": [],
            "modify_types": {"x": "varchar(128)"}}

    def test_cast_wrap_passes(self):
        new_sql = "SELECT cast(a.x AS varchar(128)) AS x, a.y AS y FROM ods.t a"
        assert check_sql_fence(self.BASE, new_sql, self.DECL) == []

    def test_pg_cast_shorthand_passes(self):
        new_sql = "SELECT a.x::varchar(128) AS x, a.y AS y FROM ods.t a"
        assert check_sql_fence(self.BASE, new_sql, self.DECL) == []

    def test_non_cast_rewrite_blocks(self):
        new_sql = "SELECT a.x || '' AS x, a.y AS y FROM ods.t a"
        v = check_sql_fence(self.BASE, new_sql, self.DECL)
        assert any("表达式被修改" in x["message"] for x in v)

    def test_cast_to_wrong_type_blocks(self):
        new_sql = "SELECT cast(a.x AS varchar(256)) AS x, a.y AS y FROM ods.t a"
        v = check_sql_fence(self.BASE, new_sql, self.DECL)
        assert any("表达式被修改" in x["message"] for x in v)

    def test_undeclared_column_cast_blocks(self):
        new_sql = "SELECT a.x AS x, cast(a.y AS varchar(128)) AS y FROM ods.t a"
        v = check_sql_fence(self.BASE, new_sql, self.DECL)
        assert any("表达式被修改" in x["message"] and "y" in x["message"] for x in v)


class TestModifyLogicWhitelist:
    """口径修改（modify_logic）：口径修改列的表达式许变（白名单放行不比对内容——
    内容锚=design_logic+闸口①'人审）；白名单外的老列照拦。"""

    BASE = "SELECT a.x AS x, a.y AS y FROM ods.t a"

    def _decl(self, mlogics=("x",)):
        return {"rule": "R1", "fields": [], "new_joins": [], "modify_types": {},
                "modify_logics": set(mlogics)}

    def test_whitelisted_expression_change_passes(self):
        new_sql = "SELECT nvl(a.x, 0) AS x, a.y AS y FROM ods.t a"
        assert check_sql_fence(self.BASE, new_sql, self._decl()) == []

    def test_non_whitelisted_change_still_blocks(self):
        new_sql = "SELECT nvl(a.x, 0) AS x, a.y || '' AS y FROM ods.t a"
        v = check_sql_fence(self.BASE, new_sql, self._decl())
        assert any("表达式被修改" in x["message"] and "'y'" in x["message"] for x in v)

    def test_whitelisted_column_loss_still_blocks(self):
        new_sql = "SELECT nvl(a.y, 0) AS y FROM ods.t a"  # x 列丢失
        v = check_sql_fence(self.BASE, new_sql, self._decl())
        assert any("丢失" in x["message"] and "'x'" in x["message"] for x in v)


class TestPlatformSqlClean:
    """vendor 预处理链接入围栏（2026-10-22）——逆向踩坑清单逐项：DWS 特有语法/
    SYSDATE/${} 占位符/注释干扰，两侧同款 clean 后 oracle 方言 parse。"""

    def test_dws_syntax_and_placeholder_pass_fence(self):
        """baseline 含 DISTRIBUTE BY/PARTITION(x)/SYSDATE/${}——vendor clean 后
        两侧正常比对（此前裸 parse 直接 ParseError 卡流程）。"""
        base = ("SELECT a.x AS x, ${P_CYCLE_ID} AS cyc FROM ods.t DISTRIBUTE BY HASH(a.x) "
                "/* 主表注释 */")
        new = ("SELECT a.x AS x, ${P_CYCLE_ID} AS cyc, a.y AS y2 FROM ods.t "
                "DISTRIBUTE BY HASH(a.x)")
        decl = {"rule": "R1", "fields": ["y2"], "new_joins": [], "modify_types": {},
                "modify_logics": set()}
        assert check_sql_fence(base, new, decl) == []

    def test_sysdate_normalized(self):
        base = "SELECT SYSDATE AS ts, a.x AS x FROM ods.t a"
        new = "SELECT SYSDATE AS ts, a.x AS x FROM ods.t a"
        assert check_sql_fence(base, new, {"rule": "R1", "fields": [], "new_joins": [],
                                           "modify_types": {}, "modify_logics": set()}) == []

    def test_unparseable_routes_manual_review(self):
        """真解析不了的形态 → 转人工披露（不装作审过，不无差别硬 fail 文案）。"""
        v = check_sql_fence("这不是 SQL", "这也不是", {"rule": "R1", "fields": [],
                                                     "new_joins": [], "modify_types": {},
                                                     "modify_logics": set()})
        assert any("转人工审查" in x["message"] for x in v)

    def test_nvl_preserved_by_oracle_dialect(self):
        """oracle 方言：NVL 原样解析不被转写 COALESCE——两侧归一稳定。"""
        base = "SELECT NVL(a.x, 0) AS x, a.y AS y FROM ods.t a"
        new = "SELECT NVL(a.x, 0) AS x, a.y AS y FROM ods.t a"
        assert check_sql_fence(base, new, {"rule": "R1", "fields": [], "new_joins": [],
                                           "modify_types": {}, "modify_logics": set()}) == []
