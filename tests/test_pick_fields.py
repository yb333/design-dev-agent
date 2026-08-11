"""
字段查询器 (pick_fields.py) 测试。

pick_fields 是 coder 写 SQL 时随取随用的工具：
- --list    规则总览（源表直取字段分布 + 加工字段清单）
- --alias   按源表别名查直取字段行（可粘贴）
- --field   查单字段详情

不测 SQL 框架生成（pick_fields 不生成框架，框架由 coder 决定）。
"""

import pytest
import sys
from pathlib import Path

CODING_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
sys.path.insert(0, str(CODING_REFS))

from pick_fields import (
    gen_direct_line,
    query_list,
    query_alias,
    query_field,
    _alias_to_table_map,
)
from slice_ts import slice_rule


# ============================================================
# 辅助
# ============================================================

def make_field(target, ftype, ttype="direct", alias="t", src_field=None, logic=""):
    sf = src_field or target
    return {
        "target_field": target,
        "field_type": ftype,
        "field_comment": target,
        "transform_type": ttype,
        "source_fields": [{"table": "ods_test_f", "field": sf, "alias": alias}],
        "design_logic": logic or f"直取 {alias}.{sf}",
    }


def make_slice(fields=None, source_tables=None, rule_code="R0001", rule_name="测试规则"):
    return {
        "rule_code": rule_code,
        "rule_name": rule_name,
        "target_table": "dws.dwb_test_f",
        "source_tables": source_tables or [
            {"schema": "ods", "table": "ods_test_f", "alias": "t"},
        ],
        "fields": fields or [],
    }


# ============================================================
# gen_direct_line
# 注意：不带缩进、不带尾逗号（调用方决定格式）；
#       不自动加 COALESCE（语义判断由 coder 做）。
# ============================================================

class TestGenDirectLine:
    def test_basic_direct_field(self):
        """direct 字段 → 别名.字段 AS 目标字段（不带 COALESCE）"""
        f = make_field("user_name", "varchar(100)")
        assert gen_direct_line(f) == "t.user_name AS user_name"

    def test_numeric_field_no_coalesce(self):
        """数值字段也不自动加 COALESCE（主键/金额语义不同，由 coder 判断）"""
        f = make_field("amount", "decimal(18,2)")
        assert gen_direct_line(f) == "t.amount AS amount"
        f2 = make_field("user_id", "bigint")
        assert gen_direct_line(f2) == "t.user_id AS user_id"

    def test_time_field(self):
        f = make_field("create_time", "timestamp")
        assert gen_direct_line(f) == "t.create_time AS create_time"

    def test_different_source_name(self):
        f = make_field("order_time", "datetime", src_field="create_time")
        assert gen_direct_line(f) == "t.create_time AS order_time"

    def test_missing_alias_returns_todo(self):
        f = make_field("amount", "int", alias="", src_field="amount")
        assert "TODO" in gen_direct_line(f)

    def test_missing_source_fields_returns_todo(self):
        f = {"target_field": "x", "field_type": "int", "transform_type": "direct",
             "source_fields": []}
        assert "TODO" in gen_direct_line(f)

    def test_no_indent_no_trailing_comma(self):
        """gen_direct_line 输出不带缩进、不带尾逗号（调用方决定格式）"""
        f = make_field("id", "int")
        line = gen_direct_line(f)
        assert not line.startswith(" ")  # 不带缩进
        assert not line.endswith(",")    # 不带尾逗号


# ============================================================
# --list 查询
# ============================================================

class TestQueryList:
    def test_list_shows_direct_distribution(self):
        """总览列出每个源表的直取字段数"""
        fields = [
            make_field("a1", "int", alias="a"),
            make_field("a2", "varchar(10)", alias="a"),
            make_field("b1", "int", alias="b"),
        ]
        sts = [{"schema": "ods", "table": "ta", "alias": "a"},
               {"schema": "dim", "table": "tb", "alias": "b"}]
        s = make_slice(fields=fields, source_tables=sts)
        result = query_list(s)
        assert "a" in result and "(ods.ta)" in result
        assert "2 个" in result  # a 有 2 个
        assert "b" in result and "(dim.tb)" in result

    def test_list_shows_processed_fields(self):
        """总览列出加工字段"""
        fields = [
            make_field("id", "int"),
            {"target_field": "total", "transform_type": "aggregate",
             "design_logic": "SUM(x)", "source_fields": [], "field_type": "decimal"},
        ]
        s = make_slice(fields=fields)
        result = query_list(s)
        assert "total" in result
        assert "aggregate" in result

    def test_list_shows_summary(self):
        fields = [make_field("id", "int"),
                  {"target_field": "total", "transform_type": "aggregate",
                   "design_logic": "", "source_fields": [], "field_type": ""}]
        s = make_slice(fields=fields)
        result = query_list(s)
        assert "直取 1" in result
        assert "加工 1" in result

    def test_list_no_direct_note(self):
        """无直取字段时给出提示"""
        fields = [{"target_field": "cnt", "transform_type": "aggregate",
                   "design_logic": "COUNT", "source_fields": [], "field_type": "int"}]
        s = make_slice(fields=fields)
        result = query_list(s)
        assert "无直取字段" in result


# ============================================================
# --alias 查询
# ============================================================

class TestQueryAlias:
    def test_returns_direct_lines_for_alias(self):
        """按别名查，返回该表的直取字段行（可粘贴格式）"""
        fields = [
            make_field("a1", "int", alias="a"),
            make_field("a2", "varchar(10)", alias="a"),
            make_field("b1", "int", alias="b"),
        ]
        sts = [{"schema": "ods", "table": "ta", "alias": "a"},
               {"schema": "ods", "table": "tb", "alias": "b"}]
        s = make_slice(fields=fields, source_tables=sts)
        result = query_alias(s, "a")
        assert "a.a1 AS a1" in result
        assert "a.a2 AS a2" in result
        assert "b.b1" not in result  # 不该混入 b 表
        assert "2 个" in result  # a 表 2 个字段

    def test_lines_have_indent_and_trailing_comma(self):
        """--alias 输出的字段行带缩进（4空格）和尾逗号（方便粘贴）"""
        fields = [make_field("id", "int", alias="t")]
        s = make_slice(fields=fields)
        result = query_alias(s, "t")
        lines = [l for l in result.split("\n") if "AS id" in l]
        assert lines
        assert lines[0].startswith("    ")  # 4 空格缩进
        assert lines[0].rstrip().endswith(",")  # 尾逗号

    def test_unknown_alias_gives_hint(self):
        """查不存在的别名 → 给出所有合法别名"""
        fields = [make_field("id", "int", alias="t")]
        sts = [{"schema": "ods", "table": "ta", "alias": "t"}]
        s = make_slice(fields=fields, source_tables=sts)
        result = query_alias(s, "xyz")
        assert "未找到" in result
        assert "t" in result  # 给出合法别名提示

    def test_alias_exists_but_no_direct(self):
        """别名存在但全是加工字段 → 友好提示"""
        fields = [{"target_field": "cnt", "transform_type": "aggregate",
                   "design_logic": "", "source_fields": [{"table": "t", "field": "x", "alias": "t"}],
                   "field_type": "int"}]
        sts = [{"schema": "ods", "table": "ta", "alias": "t"}]
        s = make_slice(fields=fields, source_tables=sts)
        result = query_alias(s, "t")
        assert "无直取字段" in result or "全是加工" in result

    def test_header_shows_table_display(self):
        """输出头部显示 schema.table 全名"""
        fields = [make_field("id", "int", alias="t")]
        sts = [{"schema": "ods", "table": "ods_test_f", "alias": "t"}]
        s = make_slice(fields=fields, source_tables=sts)
        result = query_alias(s, "t")
        assert "ods.ods_test_f" in result


# ============================================================
# --field 查询
# ============================================================

class TestQueryField:
    def test_direct_field_shows_generated_line(self):
        """直取字段查询 → 给出取值表达式行"""
        fields = [make_field("amount", "decimal(18,2)")]
        s = make_slice(fields=fields)
        result = query_field(s, "amount")
        assert "类型" in result
        assert "来源" in result
        assert "t.amount AS amount" in result  # 直取给取值行

    def test_aggregate_field_shows_design_logic(self):
        """加工字段查询 → 给出 design_logic，不生成取值行"""
        fields = [{"target_field": "total", "transform_type": "aggregate",
                   "design_logic": "按 user_id 分组 SUM", "source_fields": [],
                   "field_type": "decimal", "field_comment": "合计"}]
        s = make_slice(fields=fields)
        result = query_field(s, "total")
        assert "按 user_id 分组 SUM" in result
        assert "生成行" not in result  # 加工字段不给取值行

    def test_field_case_insensitive(self):
        """字段名大小写不敏感"""
        fields = [make_field("OrderID", "int")]
        s = make_slice(fields=fields)
        result = query_field(s, "orderid")
        assert "OrderID" in result

    def test_unknown_field_gives_fuzzy_hint(self):
        """查不存在的字段 → 模糊匹配建议"""
        fields = [make_field("order_id", "int"), make_field("order_no", "varchar(10)")]
        s = make_slice(fields=fields)
        result = query_field(s, "order")
        assert "未找到" in result
        assert "order_id" in result  # 模糊建议


# ============================================================
# 真实 ts.json 集成
# ============================================================

class TestRealTsIntegration:
    REAL_TS = [
        ("dwb_user_profile_f", "R0001"),
        ("dwb_user_center_f", "R0001"),
        ("dwb_user_center_f", "R0003"),
        ("dwb_order_center_f", "R0001"),
        ("dwb_order_center_f", "R0003"),
    ]

    @pytest.fixture
    def real_ts_path(self):
        return Path(__file__).resolve().parent.parent / "10_project_deliver"

    @pytest.mark.parametrize("asset,rule", REAL_TS)
    def test_list_works(self, real_ts_path, asset, rule):
        ts_path = real_ts_path / asset / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip(f"{ts_path} 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, rule)
        result = query_list(sliced)
        assert rule in result

    def test_order_center_r0003_alias_query(self, real_ts_path):
        """大规则按表查（90个直取分散在18个表）"""
        ts_path = real_ts_path / "dwb_order_center_f" / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip("ts.json 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, "R0003")
        # dof 是主表，应该有最多直取字段
        result = query_alias(sliced, "dof")
        assert "dwd_order_f" in result
        assert "dof.order_id AS order_id" in result

    def test_user_profile_alias_dul(self, real_ts_path):
        """user_profile 的 dim_user_level_d 表直取字段"""
        ts_path = real_ts_path / "dwb_user_profile_f" / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip("ts.json 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, "R0001")
        result = query_alias(sliced, "dul")
        assert "level_name" in result
        assert "dul.level_name AS level_name" in result

    def test_user_profile_field_lookup(self, real_ts_path):
        """查 user_profile 的某个加工字段"""
        ts_path = real_ts_path / "dwb_user_profile_f" / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip("ts.json 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, "R0001")
        # user_profile 有加工字段 age_processed
        result = query_field(sliced, "age_processed")
        assert "age_processed" in result
        assert "aggregate" in result


# ============================================================
# check_sql 兼容
# ============================================================

class TestCheckSqlCompat:
    def test_direct_line_alias_recognized_by_check_sql(self):
        """--alias 输出的字段行有 AS 别名，check_sql 能识别"""
        from check_sql import extract_select_aliases
        f = make_field("user_name", "varchar(50)")
        line = gen_direct_line(f)
        aliases = extract_select_aliases(f"SELECT {line} FROM t")
        assert "user_name" in aliases
