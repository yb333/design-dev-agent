"""纯逻辑函数补测（任务五：排查覆盖缺口）。

覆盖之前没有直接单测的纯逻辑函数：
- check_sql.py: read_sql / extract_from_tables / check_bracket_balance / check_no_select_star
- validate_ddl.py: normalize_type / parse_ddl / match_ddl_to_design
- assemble_ddl.py: split_table_ref / type_or_empty / generate_rollback
- dws_db.py: resolve_source_by_schema

只测纯逻辑（不连库、不读真实文件，输入用 str/dict/tmp_path 构造）。
不为了凑覆盖率——每个测试验证一个明确行为。
"""

import json
import pytest

from check_sql import (
    read_sql, extract_from_tables, check_bracket_balance, check_no_select_star,
)
from validate_ddl import normalize_type, parse_ddl, match_ddl_to_design
from assemble_ddl import split_table_ref, type_or_empty, generate_rollback
from dws_db import resolve_source_by_schema


# ============================================================
# check_sql.py
# ============================================================

class TestReadSql:
    def test_strips_block_comments(self, tmp_path):
        p = tmp_path / "q.sql"
        p.write_text("/* 块注释 */\nSELECT 1;", encoding="utf-8")
        # 块注释被去，留一个换行（块注释行的换行符保留）
        assert "SELECT 1;" in read_sql(str(p))
        assert "块注释" not in read_sql(str(p))

    def test_strips_line_comments(self, tmp_path):
        p = tmp_path / "q.sql"
        p.write_text("-- 行注释\nSELECT 1;", encoding="utf-8")
        result = read_sql(str(p))
        assert result.strip() == "SELECT 1;"
        assert "行注释" not in result

    def test_keeps_inline_dash(self, tmp_path):
        """行内 -- 不被误删（只删行首的 -- 注释行）。"""
        p = tmp_path / "q.sql"
        p.write_text("SELECT 'a--b' AS x;", encoding="utf-8")
        assert "a--b" in read_sql(str(p))


class TestExtractFromTables:
    def test_from_schema_table(self):
        assert "ods_test_f" in extract_from_tables("SELECT * FROM ods.ods_test_f")

    def test_join_schema_table(self):
        result = extract_from_tables(
            "SELECT * FROM ods.a JOIN dim.b ON a.id = b.id")
        assert "a" in result
        assert "b" in result

    def test_multiple_tables(self):
        result = extract_from_tables(
            "FROM ods.t1 a JOIN ods.t2 b ON a.id=b.id LEFT JOIN ods.t3 c ON b.id=c.id")
        assert sorted(set(result)) == ["t1", "t2", "t3"]

    def test_extract_from_not_treated_as_table(self):
        """EXTRACT(MINUTE FROM ts) 里的 FROM 不是表引用。"""
        result = extract_from_tables("SELECT EXTRACT(MINUTE FROM ts) FROM ods.log_f")
        assert "log_f" in result
        # 不应把 MINUTE 当表
        assert "minute" not in result


class TestCheckBracketBalance:
    def test_balanced(self):
        ok, msg = check_bracket_balance("SELECT (a+b) FROM t WHERE x IN (1,2)")
        assert ok is True
        assert msg == ""

    def test_unbalanced_extra_close(self):
        ok, msg = check_bracket_balance("SELECT (a+b))")
        assert ok is False
        assert "右括号" in msg

    def test_unbalanced_missing_close(self):
        ok, msg = check_bracket_balance("SELECT (a+b")
        assert ok is False
        assert "不平衡" in msg

    def test_brackets_in_string_ignored(self):
        """字符串里的括号不计入平衡。"""
        ok, msg = check_bracket_balance("SELECT '(' || ')' FROM t")
        assert ok is True


class TestCheckNoSelectStar:
    def test_bare_select_star_rejected(self):
        ok, msg = check_no_select_star("SELECT * FROM t ")
        assert ok is False
        assert "SELECT *" in msg

    def test_qualified_star_rejected(self):
        ok, msg = check_no_select_star("SELECT t.* FROM t")
        assert ok is False

    def test_explicit_fields_ok(self):
        ok, msg = check_no_select_star("SELECT id, name FROM t")
        assert ok is True
        assert msg == ""


# ============================================================
# validate_ddl.py
# ============================================================

class TestNormalizeType:
    def test_strips_whitespace(self):
        assert normalize_type("VARCHAR(100)") == "VARCHAR(100)"

    def test_uppercases(self):
        assert normalize_type("varchar(100)") == "VARCHAR(100)"

    def test_removes_inner_space(self):
        assert normalize_type("timestamp without time zone") == "TIMESTAMPWITHOUTTIMEZONE"


class TestParseDdl:
    def test_parses_table_and_fields(self):
        ddl = """CREATE TABLE dws.dwb_test_f (
            id BIGINT,
            name VARCHAR(100),
            amt DECIMAL(18,2),
            PRIMARY KEY (id)
        )"""
        result = parse_ddl(ddl)
        assert result is not None
        table, fields = result
        assert table == "dws.dwb_test_f"
        names = [f[0] for f in fields]
        assert "id" in names
        assert "name" in names
        assert "amt" in names

    def test_skips_constraint_lines(self):
        """PRIMARY KEY/CONSTRAINT 等约束行不入字段列表。"""
        ddl = """CREATE TABLE t (
            id BIGINT,
            CONSTRAINT pk PRIMARY KEY (id)
        )"""
        _, fields = parse_ddl(ddl)
        names = [f[0] for f in fields]
        assert "id" in names
        assert "pk" not in names  # 约束名不是字段

    def test_no_create_returns_none(self):
        assert parse_ddl("SELECT 1") is None


class TestMatchDdlToDesign:
    def test_matches_by_name(self):
        mappings = [
            {"output_table": "dwb_test_f", "fields": {"id": "BIGINT"}},
            {"output_table": "dwb_other_f", "fields": {}},
        ]
        m = match_ddl_to_design("dwb_test_f", mappings)
        assert m is not None
        assert m["output_table"] == "dwb_test_f"

    def test_case_insensitive(self):
        mappings = [{"output_table": "DWB_TEST_F", "fields": {}}]
        assert match_ddl_to_design("dwb_test_f", mappings) is not None

    def test_no_match_returns_none(self):
        mappings = [{"output_table": "dwb_other_f", "fields": {}}]
        assert match_ddl_to_design("dwb_test_f", mappings) is None


# ============================================================
# assemble_ddl.py 辅助函数
# ============================================================

class TestSplitTableRef:
    def test_with_schema(self):
        assert split_table_ref("dws.dwb_test_f") == ("dws", "dwb_test_f")

    def test_without_schema(self):
        assert split_table_ref("dwb_test_f") == ("", "dwb_test_f")

    def test_schema_with_dot_in_table(self):
        """schema.table 只在第一个点拆（表名不含点）。"""
        assert split_table_ref("a.b.c") == ("a", "b.c")


class TestTypeOrEmpty:
    def test_returns_value(self):
        assert type_or_empty("BIGINT") == "BIGINT"

    def test_empty_string(self):
        assert type_or_empty("") == ""

    def test_none_becomes_empty(self):
        """None 归一为空串（t if t else '' 的 falsy 兜底）。"""
        assert type_or_empty(None) == ""


class TestGenerateRollback:
    def test_table_rollback(self):
        out = generate_rollback("dws", "dwb_test_f")
        assert "DROP TABLE" in out
        assert "dws.dwb_test_f" in out
        assert "IF EXISTS" in out

    def test_view_rollback(self):
        out = generate_rollback("dws", "dwb_test_i", is_view=True)
        assert "DROP VIEW" in out
        assert "dws.dwb_test_i" in out


# ============================================================
# dws_db.resolve_source_by_schema
# ============================================================

class TestResolveSourceBySchema:
    def test_schema_mapping_hit(self, tmp_path):
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({
            "schema_mapping": {"fin": "fin_src"},
            "default": "default_src",
        }), encoding="utf-8")
        assert resolve_source_by_schema(str(cfg), "fin") == "fin_src"

    def test_schema_miss_raises(self, tmp_path):
        """schema 没配 mapping → raise ValueError（强制配全，不静默回退 default 掩盖）。"""
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({
            "schema_mapping": {"fin": "fin_src"},
            "default": "default_src",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="schema_mapping"):
            resolve_source_by_schema(str(cfg), "unknown")

    def test_missing_file_raises(self):
        """配置文件不存在 → raise FileNotFoundError（不静默返回空掩盖）。"""
        with pytest.raises(FileNotFoundError):
            resolve_source_by_schema("/nonexistent/db.json", "fin")

    def test_schema_miss_no_default_raises(self, tmp_path):
        """schema 没配 mapping（即使配置里没 default）→ raise ValueError。"""
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({"schema_mapping": {"fin": "fin_src"}}), encoding="utf-8")
        with pytest.raises(ValueError):
            resolve_source_by_schema(str(cfg), "unknown")

    def test_source_not_exist_raises(self, tmp_path):
        """指定的 source 不在配置里 → raise（不静默换第一个数据源掩盖）。"""
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            pytest.skip("psycopg2 未安装，跳过 PsycopgExecutor 测试")
        from dws_db import PsycopgExecutor
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({
            "sources": {"src1": {"host": "h", "roles": {"etl": {"user": "u", "password": "p"}}}},
            "default": "src1",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="不在配置里"):
            PsycopgExecutor(str(cfg), source_name="nonexistent")

    def test_no_source_no_default_raises(self, tmp_path):
        """既没传 source 也没配 default → raise（不静默用第一个）。"""
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            pytest.skip("psycopg2 未安装，跳过 PsycopgExecutor 测试")
        from dws_db import PsycopgExecutor
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({
            "sources": {"src1": {"host": "h", "roles": {"etl": {"user": "u", "password": "p"}}}},
        }), encoding="utf-8")  # 无 default
        with pytest.raises(ValueError, match="未指定数据源"):
            PsycopgExecutor(str(cfg))  # 不传 source_name
