"""exporter_common 单元测试"""

import re
import time

import pytest

from exporter_common import (
    ParsedSQL,
    FIXED_PARAMS,
    DEFAULT_JOB_PARAMS,
    AUDIT_FIELDS,
    _extract_alias,
    _extract_select_list,
    _find_main_select,
    _find_matching_paren,
    _parse_markdown_table_row,
    _split_by_comma,
    _strip_line_comments,
    generate_rule_codes,
    generate_rule_group_code,
    load_export_state,
    parse_design_md,
    parse_sql_file,
    parse_view_ddl,
    save_export_state,
    scan_etl_variables,
)


# ── generate_rule_codes ─────────────────────────────────


class TestGenerateRuleCodes:

    def test_生成单个规则码(self):
        codes = generate_rule_codes(count=1, base_ts=123456)
        assert codes == ["UR123456"]

    def test_生成多个规则码递增(self):
        codes = generate_rule_codes(count=3, base_ts=100)
        assert codes == ["UR000100", "UR000101", "UR000102"]

    def test_规则码溢出取模(self):
        codes = generate_rule_codes(count=2, base_ts=999999)
        assert codes == ["UR999999", "UR000000"]

    def test_不传base_ts使用时间戳(self):
        before = int(time.time()) % 1_000_000
        codes = generate_rule_codes(count=1)
        after = int(time.time()) % 1_000_000
        assert len(codes) == 1
        assert codes[0].startswith("UR")
        num = int(codes[0][2:])
        assert before <= num <= after + 1  # +1 容忍秒级误差

    def test_生成零个规则码(self):
        assert generate_rule_codes(count=0, base_ts=100) == []


# ── generate_rule_group_code ─────────────────────────────


class TestGenerateRuleGroupCode:

    def test_生成规则组码(self):
        code = generate_rule_group_code(base_ts=123456)
        assert code == "GR123456"

    def test_不传base_ts使用时间戳(self):
        before = int(time.time()) % 1_000_000
        code = generate_rule_group_code()
        after = int(time.time()) % 1_000_000
        assert code.startswith("GR")
        num = int(code[2:])
        assert before <= num <= after + 1

    def test_规则组码格式(self):
        code = generate_rule_group_code(base_ts=42)
        assert re.fullmatch(r"GR\d{6}", code)


# ── ParsedSQL dataclass ──────────────────────────────────


class TestParsedSQLDataclass:

    def test_ParsedSQL默认值(self):
        p = ParsedSQL()
        assert p.sql_path == ""
        assert p.target_schema == ""
        assert p.target_table == ""
        assert p.target_table_full == ""
        assert p.query_statement == ""
        assert p.target_columns == []
        assert p.source_columns == []
        assert p.variables == set()

    def test_ParsedSQL自定义值(self):
        p = ParsedSQL(
            sql_path="/tmp/a.sql",
            target_schema="slprd",
            target_table="dwb_test_f",
            target_table_full="slprd.dwb_test_f",
            query_statement="SELECT 1",
            target_columns=["id"],
            source_columns=["id"],
            variables={"P_CYCLE_ID"},
        )
        assert p.target_schema == "slprd"
        assert p.target_table == "dwb_test_f"
        assert "P_CYCLE_ID" in p.variables


# ── _split_by_comma ─────────────────────────────────────


class TestSplitByComma:

    def test_简单逗号分割(self):
        assert _split_by_comma("a, b, c") == ["a", "b", "c"]

    def test_嵌套括号不分割(self):
        assert _split_by_comma("func(a,b), x") == ["func(a,b)", "x"]

    def test_空字符串(self):
        assert _split_by_comma("") == []

    def test_单元素(self):
        assert _split_by_comma("only") == ["only"]


# ── _find_matching_paren ─────────────────────────────────


class TestFindMatchingParen:

    def test_简单匹配(self):
        assert _find_matching_paren("(abc)", 0) == 4

    def test_嵌套匹配(self):
        assert _find_matching_paren("((a))", 0) == 4

    def test_不匹配返回负一(self):
        assert _find_matching_paren("(abc", 0) == -1


# ── _parse_markdown_table_row ────────────────────────────


class TestParseMarkdownTableRow:

    def test_标准表格行(self):
        cells = _parse_markdown_table_row("| key | val |")
        assert cells == ["", "key", "val", ""]

    def test_分隔行返回None(self):
        assert _parse_markdown_table_row("|---|---|") is None

    def test_非表格行返回None(self):
        assert _parse_markdown_table_row("plain text") is None


# ── _extract_alias ───────────────────────────────────────


class TestExtractAlias:

    def test_简单表名(self):
        assert _extract_alias("p.product_id") == "product_id"

    def test_AS别名(self):
        assert _extract_alias("COALESCE(x, 0) AS amt") == "amt"

    def test_字符串AS(self):
        assert _extract_alias("'N' AS del_flag") == "del_flag"

    def test_无别名函数(self):
        assert _extract_alias("CURRENT_TIMESTAMP") == "CURRENT_TIMESTAMP"

    def test_CASE语句无别名(self):
        assert _extract_alias("CASE WHEN a THEN b END") == ""

    def test_注释截断(self):
        # After stripping "-- comment", extracts last \w+ token: "col" (dot is not \w)
        assert _extract_alias("p.col -- comment") == "col"


# ── parse_sql_file ───────────────────────────────────────


class TestParseSqlFile:

    def test_TRUNCATE_INSERT模式(self, tmp_path):
        sql = (
            "TRUNCATE TABLE slprd.dwb_test;\n"
            "INSERT INTO slprd.dwb_test (id, name) SELECT id, name FROM src.t;"
        )
        f = tmp_path / "test.sql"
        f.write_text(sql, encoding="utf-8")
        result = parse_sql_file(f)
        assert result.target_schema == "slprd"
        assert result.target_table == "dwb_test"
        assert result.target_table_full == "slprd.dwb_test"
        assert "TRUNCATE" not in result.query_statement
        assert result.target_columns == ["id", "name"]

    def test_INSERT_WITH_CTE模式(self, tmp_path):
        sql = (
            "INSERT INTO slprd.dwb_order (order_id, amount)\n"
            "WITH cte AS (SELECT order_id, SUM(price) AS amount FROM src.orders GROUP BY order_id)\n"
            "SELECT order_id, amount FROM cte;"
        )
        f = tmp_path / "test_cte.sql"
        f.write_text(sql, encoding="utf-8")
        result = parse_sql_file(f)
        assert result.target_schema == "slprd"
        assert result.target_table == "dwb_order"
        assert "WITH cte" in result.query_statement
        assert result.target_columns == ["order_id", "amount"]

    def test_提取变量占位符(self, tmp_path):
        sql = (
            "INSERT INTO slprd.dwb_test (cycle_id, data_date)\n"
            "SELECT '${P_CYCLE_ID}', '${P_DATA_DATE}' FROM src.t;"
        )
        f = tmp_path / "test_vars.sql"
        f.write_text(sql, encoding="utf-8")
        result = parse_sql_file(f)
        assert "P_CYCLE_ID" in result.variables
        assert "P_DATA_DATE" in result.variables

    def test_空文件(self, tmp_path):
        f = tmp_path / "empty.sql"
        f.write_text("", encoding="utf-8")
        result = parse_sql_file(f)
        assert result.target_schema == ""
        assert result.target_table == ""
        assert result.target_columns == []
        assert result.variables == set()
        assert result.source_columns == []

    def test_提取目标列列表(self, tmp_path):
        sql = (
            "INSERT INTO slprd.dwb_product (\n"
            "    product_id,\n"
            "    product_name,\n"
            "    del_flag\n"
            ") SELECT product_id, product_name, 'N' AS del_flag FROM src.product;"
        )
        f = tmp_path / "test_cols.sql"
        f.write_text(sql, encoding="utf-8")
        result = parse_sql_file(f)
        assert result.target_columns == ["product_id", "product_name", "del_flag"]
        assert result.source_columns == ["product_id", "product_name", "del_flag"]


# ── parse_design_md ──────────────────────────────────────


class TestParseDesignMd:

    def test_提取目标表(self, tmp_path):
        md = "**目标表**: `slprd.dwb_product_center_f`\n\n一些其他内容"
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert result["target_table"] == "slprd.dwb_product_center_f"
        assert result["target_table_short"] == "dwb_product_center_f"

    def test_提取调度配置(self, tmp_path):
        md = (
            "**目标表**: `slprd.dwb_test_f`\n\n"
            "## 1. 调度配置\n\n"
            "| 配置项 | 值 |\n"
            "|--------|-----|\n"
            "| 项目名称 | 数仓项目 |\n"
            "| 任务组名称 | DWB组 |\n"
            "| 调度周期 | 0 0 2 * * ? |\n"
            "| 责任人 | 张三 |\n"
            "| 上游依赖 | 无 |\n"
            "| 调度任务 | 数仓项目/DWB组/产品中心 |\n"
            "\n---\n"
        )
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert result["project_name"] == "数仓项目"
        assert result["task_group"] == "DWB组"
        assert result["cron_expr"] == "0 0 2 * * ?"
        assert result["owner"] == "张三"
        assert result["upstream_deps"] == "无"

    def test_提取执行平台配置(self, tmp_path):
        """测试执行平台配置解析。

        注意：parse_design_md 使用子串匹配（`if match_key in key`），
        因此 "项目编码" 会匹配 "子项目编码"。为避免断言歧义，
        fixture 中只包含不存在子串碰撞的配置项。
        """
        md = (
            "**目标表**: `slprd.dwb_test_f`\n\n"
            "## 1. 调度配置\n\n"
            "| 配置项 | 值 |\n"
            "|--------|-----|\n"
            "| 项目名称 | 数仓项目 |\n"
            "| 调度周期 | 0 0 2 * * ? |\n"
            "\n### 执行平台配置\n\n"
            "| 配置项 | 值 |\n"
            "|--------|-----|\n"
            "| 子项目编码 | SUB001 |\n"
            "| 子项目中文名 | 产品子项目 |\n"
            "| 数据源 | dws_prod |\n"
            "| 业务责任人 | 李四 |\n"
            "\n---\n"
        )
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert result["exec_sub_project_code"] == "SUB001"
        assert result["exec_sub_project_cn_name"] == "产品子项目"
        assert result["exec_data_source"] == "dws_prod"
        assert result["exec_business_owner"] == "李四"

    def test_提取上游任务依赖(self, tmp_path):
        md = (
            "**目标表**: `slprd.dwb_test_f`\n\n"
            "## 1. 调度配置\n\n"
            "| 配置项 | 值 |\n"
            "|--------|-----|\n"
            "| 项目名称 | 数仓项目 |\n"
            "\n### 上游任务依赖\n\n"
            "| 来源表 | 调度任务 | 执行路径 | 依赖参数 |\n"
            "|--------|----------|----------|----------|\n"
            "| dim.dim_product | dim/产品维度/ods_sync | etl/dim/product | {\"V_CYCLE_ID\":\"${P_CYCLE_ID}\"} |\n"
            "\n---\n"
        )
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert len(result["upstream_tasks"]) == 1
        task = result["upstream_tasks"][0]
        assert task["source_table"] == "dim.dim_product"
        assert task["schedule_task"] == "dim/产品维度/ods_sync"
        assert task["exec_path"] == "etl/dim/product"

    def test_无调度配置返回空(self, tmp_path):
        md = "**目标表**: `slprd.dwb_test_f`\n\n一些内容，没有调度配置章节\n"
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert result["project_name"] == ""
        assert result["cron_expr"] == ""
        assert result["upstream_tasks"] == []

    def test_消费视图检测(self, tmp_path):
        md = (
            "**目标表**: `slprd.dwb_test_f`\n\n"
            "## 2. 分段策略\n\n"
            "本表需要创建消费视图供下游查询使用。\n\n"
            "## 1. 调度配置\n\n"
            "| 配置项 | 值 |\n"
            "|--------|-----|\n"
            "| 项目名称 | 数仓项目 |\n"
            "\n---\n"
        )
        f = tmp_path / "design.md"
        f.write_text(md, encoding="utf-8")
        result = parse_design_md(f)
        assert result["wrap_view"] is True
        # _f → _i 视图命名
        assert result["view_name"] == "slprd.dwb_test_i"


# ── parse_view_ddl ───────────────────────────────────────


class TestParseViewDdl:

    def test_扫描CREATE_VIEW文件(self, tmp_path):
        ddl = tmp_path / "ddl"
        ddl.mkdir()
        (ddl / "v1.sql").write_text(
            "CREATE VIEW slprd.dwb_test_i AS SELECT id, name FROM slprd.dwb_test_f;",
            encoding="utf-8",
        )
        (ddl / "regular.sql").write_text(
            "CREATE TABLE slprd.other (id INT);",
            encoding="utf-8",
        )
        results = parse_view_ddl(ddl)
        assert len(results) == 1
        assert results[0]["file_path"] == "v1.sql"
        assert results[0]["view_name"] == "slprd.dwb_test_i"
        assert "CREATE VIEW" in results[0]["ddl_statement"]

    def test_空目录(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert parse_view_ddl(empty) == []

    def test_不存在的目录(self, tmp_path):
        assert parse_view_ddl(tmp_path / "no_such_dir") == []

    def test_CREATE_OR_REPLACE_VIEW(self, tmp_path):
        ddl = tmp_path / "ddl"
        ddl.mkdir()
        (ddl / "v_replace.sql").write_text(
            "CREATE OR REPLACE VIEW slprd.dwb_order_i AS SELECT * FROM slprd.dwb_order_f;",
            encoding="utf-8",
        )
        results = parse_view_ddl(ddl)
        assert len(results) == 1
        assert results[0]["view_name"] == "slprd.dwb_order_i"
        assert "OR REPLACE" in results[0]["ddl_statement"]


# ── scan_etl_variables ───────────────────────────────────


class TestScanEtlVariables:

    def test_扫描变量(self, tmp_path):
        etl = tmp_path / "etl"
        etl.mkdir()
        (etl / "e1.sql").write_text(
            "SELECT '${P_CYCLE_ID}', '${P_DATA_DATE}' FROM t;",
            encoding="utf-8",
        )
        result = scan_etl_variables(etl)
        assert "P_CYCLE_ID" in result
        assert "P_DATA_DATE" in result

    def test_空目录(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert scan_etl_variables(empty) == set()

    def test_多文件合并(self, tmp_path):
        etl = tmp_path / "etl"
        etl.mkdir()
        (etl / "a.sql").write_text("SELECT '${P_CYCLE_ID}' FROM t;", encoding="utf-8")
        (etl / "b.sql").write_text("SELECT '${P_DATA_DATE}' FROM t;", encoding="utf-8")
        (etl / "c.sql").write_text("SELECT '${P_CYCLE_ID}', '${P_ETL_DATE}' FROM t;", encoding="utf-8")
        result = scan_etl_variables(etl)
        assert result == {"P_CYCLE_ID", "P_DATA_DATE", "P_ETL_DATE"}


# ── load_export_state / save_export_state ────────────────


class TestExportState:

    def test_加载不存在的状态(self, tmp_path):
        assert load_export_state(tmp_path) == {}

    def test_保存并加载状态(self, tmp_path):
        state = {"last_export": "2026-01-01", "rule_offset": 42}
        save_export_state(tmp_path, state)
        loaded = load_export_state(tmp_path)
        assert loaded == state

    def test_保存创建目录(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        save_export_state(nested, {"key": "val"})
        assert nested.exists()
        assert load_export_state(nested) == {"key": "val"}
