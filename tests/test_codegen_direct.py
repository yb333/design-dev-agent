"""
直取字段骨架生成器 (codegen_direct.py) 测试。

不依赖数据库——测的是生成逻辑：
- direct 字段：COALESCE 默认值按 field_type 推断
- assign 字段：审计字段固定 4 行
- aggregate/计算字段：留 TODO 占位
- FROM/JOIN/WHERE 骨架
- CTE 骨架（join_safety 非 unique 的表）
- 增量 filter 进 WHERE
- 降级：缺 alias → TODO，不崩
- check_sql 兼容：生成的骨架能过静态对比

数据工厂复用 conftest 的 make_ts_json。
"""

import pytest
import sys
from pathlib import Path

# 脚本目录
CODING_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
sys.path.insert(0, str(CODING_REFS))

from codegen_direct import (
    infer_default,
    gen_direct_field_line,
    gen_assign_field_line,
    gen_aggregate_todo,
    gen_select_fields,
    gen_from_join,
    gen_select_sql,
    _cte_name_for_table,
    _is_chinese_filter,
)
from slice_ts import slice_rule


# ============================================================
# 辅助：构造切片
# ============================================================

def make_slice(fields=None, joins=None, source_tables=None, join_safety=None,
               grain=None, incremental=None, business_key=None):
    """构造一个切片 dict，用于直接测生成函数。"""
    return {
        "rule_code": "R0001",
        "rule_name": "测试规则",
        "target_table": "dws.dwb_test_f",
        "design_intent": "测试",
        "load_mode": "truncate_table",
        "incremental": incremental or {},
        "source_tables": source_tables or [
            {"schema": "ods", "table": "ods_test_f", "alias": "t"},
        ],
        "joins": joins or [
            {"alias": "t", "type": "main", "condition": "", "filter": ""},
        ],
        "join_safety": join_safety or [],
        "grain": grain or {"input": "源", "output": "目标", "change": "无变化"},
        "ctes": [],
        "fields": fields or [],
        "field_count": len(fields or []),
        "_global": {
            "audit_fields": {
                "del_flag": {"type": "NVARCHAR(1)", "default": "'N'"},
                "crt_cycle_id": {"type": "BIGINT", "default": "'${P_CYCLE_ID}'"},
                "last_upd_cycle_id": {"type": "BIGINT", "default": "'${P_CYCLE_ID}'"},
                "dw_last_update_date": {"type": "TIMESTAMP(0)", "default": "CURRENT_TIMESTAMP"},
            },
            "business_key": business_key or ["id"],
            "distribution_key": ["id"],
            "target_schema": "dws",
            "exec_params": {},
        },
    }


def make_field(target, ftype, ttype="direct", alias="t", src_field=None, logic=""):
    """构造一个字段 dict。src_field=None 时用 target 同名。"""
    sf = src_field or target
    return {
        "target_field": target,
        "field_type": ftype,
        "field_comment": target,
        "transform_type": ttype,
        "source_fields": [{"table": "ods_test_f", "field": sf, "alias": alias}],
        "design_logic": logic or f"直取 {alias}.{sf}",
    }


# ============================================================
# infer_default 测试
# ============================================================

class TestInferDefault:
    def test_numeric_types_return_zero(self):
        for t in ("int", "integer", "bigint", "smallint", "decimal", "numeric",
                  "float", "double", "DECIMAL(18,2)", "NUMBER(10,2)"):
            assert infer_default(t) == "0", f"{t} 应返回 0"

    def test_string_types_return_empty(self):
        for t in ("varchar", "char", "text", "nvarchar", "VARCHAR(100)",
                  "NVARCHAR2(50)", "clob"):
            assert infer_default(t) == "''", f"{t} 应返回 ''"

    def test_time_types_return_none(self):
        for t in ("date", "datetime", "timestamp", "TIMESTAMP(0)",
                  "TIMESTAMP(0) WITHOUT TIME ZONE", "time"):
            assert infer_default(t) is None, f"{t} 应返回 None"

    def test_empty_type_returns_none(self):
        assert infer_default("") is None
        assert infer_default(None) is None

    def test_unknown_type_returns_none(self):
        # 布尔类不 COALESCE
        assert infer_default("boolean") is None
        assert infer_default("bit") is None


# ============================================================
# direct 字段生成测试
# ============================================================

class TestGenDirectField:
    def test_numeric_field_gets_coalesce_zero(self):
        f = make_field("amount", "decimal(18,2)")
        line = gen_direct_field_line(f, "R0001")
        assert "COALESCE(t.amount, 0) AS amount" == line.strip()

    def test_string_field_gets_coalesce_empty(self):
        f = make_field("user_name", "varchar(100)")
        line = gen_direct_field_line(f, "R0001")
        assert "COALESCE(t.user_name, '') AS user_name" == line.strip()

    def test_time_field_no_coalesce(self):
        f = make_field("create_time", "timestamp")
        line = gen_direct_field_line(f, "R0001")
        assert "t.create_time AS create_time" == line.strip()

    def test_field_with_different_source_name(self):
        f = make_field("order_time", "datetime", src_field="create_time")
        line = gen_direct_field_line(f, "R0001")
        assert "t.create_time AS order_time" in line

    def test_missing_alias_returns_todo(self):
        f = make_field("amount", "int", alias="", src_field="amount")
        line = gen_direct_field_line(f, "R0001")
        assert "TODO" in line
        assert "amount" in line

    def test_missing_source_fields_returns_todo(self):
        f = {"target_field": "amount", "field_type": "int", "transform_type": "direct",
             "source_fields": [], "design_logic": ""}
        line = gen_direct_field_line(f, "R0001")
        assert "TODO" in line

    def test_unknown_type_gets_review_comment(self):
        f = make_field("flag", "", alias="t", src_field="flag")
        line = gen_direct_field_line(f, "R0001")
        assert "t.flag AS flag" in line
        assert "REVIEW" in line


# ============================================================
# assign 字段生成测试
# ============================================================

class TestGenAssignField:
    def test_audit_fields_generate_fixed_lines(self):
        assert gen_assign_field_line({"target_field": "del_flag"}) is not None
        assert "'N'" in gen_assign_field_line({"target_field": "del_flag"})
        assert "${P_CYCLE_ID}" in gen_assign_field_line({"target_field": "crt_cycle_id"})
        assert "${P_CYCLE_ID}" in gen_assign_field_line({"target_field": "last_upd_cycle_id"})
        assert "CURRENT_TIMESTAMP" in gen_assign_field_line({"target_field": "dw_last_update_date"})

    def test_non_audit_assign_returns_none(self):
        # assign 但非审计字段 → 返回 None（调用方改用 TODO）
        assert gen_assign_field_line({"target_field": "custom_flag"}) is None


# ============================================================
# aggregate TODO 测试
# ============================================================

class TestGenAggregateTodo:
    def test_aggregate_field_becomes_todo(self):
        f = {"target_field": "total_amt", "transform_type": "aggregate",
             "design_logic": "按 user_id 分组 SUM 金额"}
        line = gen_aggregate_todo(f, "R0001")
        assert "TODO" in line
        assert "total_amt" in line
        assert "SUM 金额" in line

    def test_long_design_logic_truncated(self):
        f = {"target_field": "x", "transform_type": "aggregate",
             "design_logic": "很" * 200}
        line = gen_aggregate_todo(f, "R0001")
        assert len(line) < 200  # 被截断


# ============================================================
# gen_select_fields 整合测试
# ============================================================

class TestGenSelectFields:
    def test_mixed_field_types(self):
        fields = [
            make_field("id", "bigint"),
            make_field("name", "varchar(50)"),
            {"target_field": "total", "transform_type": "aggregate",
             "design_logic": "SUM 金额"},
            {"target_field": "del_flag", "transform_type": "assign", "design_logic": ""},
        ]
        lines = gen_select_fields(make_slice(fields=fields))
        joined = "\n".join(lines)
        assert "COALESCE(t.id, 0) AS id" in joined
        assert "COALESCE(t.name, '') AS name" in joined
        assert "TODO" in joined  # aggregate
        assert "'N' AS del_flag" in joined  # assign

    def test_field_order_preserved(self):
        fields = [
            make_field("c", "int"),
            make_field("a", "int"),
            make_field("b", "int"),
        ]
        lines = gen_select_fields(make_slice(fields=fields))
        # 顺序应该和 fields 一致
        joined = "\n".join(lines)
        assert joined.index("c") < joined.index("a") < joined.index("b")


# ============================================================
# CTE 名映射测试
# ============================================================

class TestCteName:
    def test_strip_prefix_and_suffix(self):
        assert _cte_name_for_table("dwd_payment_f") == "cte_payment"
        assert _cte_name_for_table("dim_user_level_d") == "cte_user_level"
        assert _cte_name_for_table("ods_order_detail") == "cte_order_detail"

    def test_no_prefix(self):
        assert _cte_name_for_table("user_f") == "cte_user"


# ============================================================
# 中文 filter 识别测试
# ============================================================

class TestChineseFilter:
    def test_chinese_filter_detected(self):
        assert _is_chinese_filter("取省份名称") is True
        assert _is_chinese_filter("CTE 聚合结果") is True
        assert _is_chinese_filter("关联订单聚合中间表(R0001)") is True

    def test_sql_filter_not_detected(self):
        assert _is_chinese_filter("pay_status='SUCCESS'") is False
        assert _is_chinese_filter("dt >= '2025-01-01'") is False

    def test_empty(self):
        assert _is_chinese_filter("") is False


# ============================================================
# FROM/JOIN/WHERE 骨架测试
# ============================================================

class TestFromJoin:
    def test_simple_single_table(self):
        s = make_slice(
            source_tables=[{"schema": "ods", "table": "ods_test_f", "alias": "t"}],
            joins=[{"alias": "t", "type": "main", "condition": "", "filter": ""}],
        )
        result = gen_from_join(s, {})
        assert "FROM ods.ods_test_f t" in result
        assert "WHERE t.del_flag = 'N'" in result

    def test_left_join_dim_with_del_flag(self):
        s = make_slice(
            source_tables=[
                {"schema": "ods", "table": "ods_main_f", "alias": "t"},
                {"schema": "dim", "table": "dim_attr_d", "alias": "d"},
            ],
            joins=[
                {"alias": "t", "type": "main", "condition": "", "filter": ""},
                {"alias": "d", "type": "LEFT JOIN", "condition": "t.id = d.id", "filter": ""},
            ],
        )
        result = gen_from_join(s, {})
        assert "FROM ods.ods_main_f t" in result
        assert "LEFT JOIN dim.dim_attr_d d ON t.id = d.id AND d.del_flag = 'N'" in result

    def test_cte_alias_no_schema(self):
        """joins 里有 CTE 别名（不在 source_tables）→ 直接用别名当表名，不加 schema。"""
        s = make_slice(
            source_tables=[
                {"schema": "ods", "table": "ods_main_f", "alias": "t"},
            ],
            joins=[
                {"alias": "t", "type": "main", "condition": "", "filter": ""},
                {"alias": "agg", "type": "LEFT JOIN",
                 "condition": "t.id = agg.id", "filter": "CTE 聚合结果"},
            ],
        )
        result = gen_from_join(s, {})
        assert "FROM ods.ods_main_f t" in result
        assert "LEFT JOIN agg ON t.id = agg.id" in result
        # 中文 filter 不应拼进 SQL
        assert "CTE" not in result.split("ON")[1] if "ON" in result else True

    def test_chinese_filter_skipped(self):
        """filter 是中文说明时跳过，不拼进 SQL。"""
        s = make_slice(
            source_tables=[
                {"schema": "dim", "table": "dim_region_f", "alias": "drf"},
            ],
            joins=[
                {"alias": "drf", "type": "main", "condition": "", "filter": ""},
                {"alias": "drf_city", "type": "LEFT JOIN",
                 "condition": "t.city_code = drf_city.region_code",
                 "filter": "取城市名称"},
            ],
        )
        result = gen_from_join(s, {})
        assert "取城市名称" not in result

    def test_sql_filter_included(self):
        """filter 是合法 SQL 片段时拼进 JOIN。"""
        s = make_slice(
            source_tables=[
                {"schema": "ods", "table": "ods_main_f", "alias": "t"},
                {"schema": "ods", "table": "ods_pay_f", "alias": "p"},
            ],
            joins=[
                {"alias": "t", "type": "main", "condition": "", "filter": ""},
                {"alias": "p", "type": "LEFT JOIN",
                 "condition": "t.id = p.id", "filter": "pay_status='SUCCESS'"},
            ],
        )
        result = gen_from_join(s, {})
        assert "pay_status='SUCCESS'" in result

    def test_incremental_filter_in_where(self):
        s = make_slice(
            incremental={"filter": "t.update_time >= '${BIZ_DATE_START}' AND t.update_time < '${BIZ_DATE_END}'"},
        )
        result = gen_from_join(s, {})
        assert "BIZ_DATE_START" in result
        assert "AND" in result

    def test_aggregate_grain_adds_groupby_todo(self):
        s = make_slice(grain={"input": "多行", "output": "一行=一个用户", "change": "多行聚合"})
        result = gen_from_join(s, {})
        assert "GROUP BY" in result or "TODO" in result

    def test_cte_internal_aggregate_no_groupby(self):
        """grain.change='CTE内部聚合' → 主查询不加 GROUP BY。"""
        s = make_slice(grain={"input": "源", "output": "目标", "change": "无变化（CTE内部聚合）"})
        result = gen_from_join(s, {})
        assert "GROUP BY" not in result


# ============================================================
# 完整 SQL 生成测试
# ============================================================

class TestGenSelectSql:
    def test_complete_sql_has_all_sections(self):
        fields = [
            make_field("id", "bigint"),
            make_field("name", "varchar(50)"),
            {"target_field": "del_flag", "transform_type": "assign", "design_logic": ""},
            {"target_field": "crt_cycle_id", "transform_type": "assign", "design_logic": ""},
            {"target_field": "last_upd_cycle_id", "transform_type": "assign", "design_logic": ""},
            {"target_field": "dw_last_update_date", "transform_type": "assign", "design_logic": ""},
        ]
        s = make_slice(fields=fields)
        sql = gen_select_sql(s)
        assert "SELECT" in sql
        assert "FROM ods.ods_test_f t" in sql
        assert "WHERE t.del_flag = 'N'" in sql
        assert "COALESCE(t.id, 0) AS id" in sql
        assert "'N' AS del_flag" in sql
        assert "${P_CYCLE_ID}" in sql
        assert sql.strip().endswith(";")

    def test_sql_ends_with_semicolon(self):
        s = make_slice(fields=[make_field("id", "int")])
        sql = gen_select_sql(s)
        assert sql.rstrip().endswith(";")

    def test_file_header_contains_rule_info(self):
        s = make_slice(fields=[make_field("id", "int")])
        s["rule_name"] = "订单汇总"
        s["design_intent"] = "全量加工"
        sql = gen_select_sql(s)
        assert "R0001" in sql
        assert "订单汇总" in sql
        assert "全量加工" in sql

    def test_aggregate_fields_all_todo(self):
        """纯聚合规则：所有 aggregate 字段都是 TODO。"""
        fields = [
            {"target_field": "cnt", "transform_type": "aggregate", "design_logic": "COUNT(*)"},
            {"target_field": "total", "transform_type": "aggregate", "design_logic": "SUM(amt)"},
        ]
        s = make_slice(fields=fields, grain={"change": "多行聚合"})
        sql = gen_select_sql(s)
        assert "TODO" in sql
        assert "COUNT" in sql
        assert "SUM" in sql


# ============================================================
# 真实 ts.json 切片集成测试
# ============================================================

class TestRealTsIntegration:
    """用真实产出 ts.json 跑切片+生成，验证不崩 + 结构完整。"""

    REAL_TS = [
        ("dwb_user_profile_f", "R0001"),  # 92% 直取
        ("dwb_user_center_f", "R0001"),   # 聚合中间表
        ("dwb_user_center_f", "R0003"),   # 多CTE宽表
        ("dwb_order_center_f", "R0001"),  # 聚合中间表
        ("dwb_shop_center_f", "R0001"),
        ("dwb_product_center_f", "R0001"),
    ]

    @pytest.fixture
    def real_ts_path(self):
        base = Path(__file__).resolve().parent.parent / "10_project_deliver"
        return base

    @pytest.mark.parametrize("asset,rule", REAL_TS)
    def test_generate_from_real_ts(self, real_ts_path, asset, rule):
        """从真实 ts.json 生成，不崩且结构完整。"""
        ts_path = real_ts_path / asset / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip(f"{ts_path} 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, rule)
        sql = gen_select_sql(sliced)
        # 基本结构检查
        assert "SELECT" in sql
        assert "FROM" in sql
        assert "WHERE" in sql
        assert sql.rstrip().endswith(";")
        # 文件头有规则信息
        assert rule in sql

    def test_user_profile_mostly_direct(self, real_ts_path):
        """user_profile 92% 直取 → 生成的 SQL 里 COALESCE 占大头，TODO 少。"""
        ts_path = real_ts_path / "dwb_user_profile_f" / "ddlc_design_dev" / "ts.json"
        if not ts_path.exists():
            pytest.skip("user_profile ts.json 不存在")
        import json
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        sliced = slice_rule(ts, "R0001")
        sql = gen_select_sql(sliced)
        coalesce_count = sql.count("COALESCE(")
        todo_count = sql.count("-- TODO")
        # user_profile 92% 直取 → COALESCE 应远多于 TODO
        assert coalesce_count > 30, f"直取字段应生成大量 COALESCE，实际 {coalesce_count}"
        assert todo_count < coalesce_count, f"直灌场景 TODO({todo_count}) 应少于 COALESCE({coalesce_count})"


# ============================================================
# check_sql 兼容性测试
# ============================================================

class TestCheckSqlCompat:
    def test_generated_sql_passes_check_for_direct_only(self):
        """纯 direct+assign 的生成 SQL 应能过 check_sql（字段覆盖完整）。"""
        from check_sql import check_sql

        # 构造字段：2 个 direct + 4 个 assign 审计字段
        fields = [
            make_field("id", "bigint"),
            make_field("name", "varchar(50)"),
            {"target_field": "del_flag", "transform_type": "assign",
             "source_fields": [], "design_logic": ""},
            {"target_field": "crt_cycle_id", "transform_type": "assign",
             "source_fields": [], "design_logic": ""},
            {"target_field": "last_upd_cycle_id", "transform_type": "assign",
             "source_fields": [], "design_logic": ""},
            {"target_field": "dw_last_update_date", "transform_type": "assign",
             "source_fields": [], "design_logic": ""},
        ]
        ts = {
            "design": {
                "audit_fields": {
                    "del_flag": {}, "crt_cycle_id": {}, "last_upd_cycle_id": {},
                    "dw_last_update_date": {},
                },
                "business_key": ["id"],
            },
            "rules": {
                "R0001": {
                    "source_tables": [{"table": "ods_test_f"}],
                    "field_targets": ["id", "name", "del_flag", "crt_cycle_id",
                                      "last_upd_cycle_id", "dw_last_update_date"],
                    "ctes": [],
                }
            },
        }
        s = make_slice(fields=fields)
        sql = gen_select_sql(s)
        # check_sql 应该不报字段覆盖缺失（因为 direct+assign 都有 AS 别名）
        issues = check_sql(sql, ts, "R0001")
        # 允许报"多出字段"（CTE 名等），但不应该报"缺少字段"
        missing_issues = [i for i in issues if "缺少字段" in i or "缺少审计" in i]
        assert not missing_issues, f"生成 SQL 缺字段: {missing_issues}"
