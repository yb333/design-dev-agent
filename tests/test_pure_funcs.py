"""纯逻辑函数补测（任务五：排查覆盖缺口）。

覆盖之前没有直接单测的纯逻辑函数：
- check_sql.py: read_sql / extract_from_tables / check_bracket_balance / check_no_select_star
- assemble_ddl.py: split_table_ref / type_or_empty / generate_rollback
- dws_db.py: resolve_source_by_schema

只测纯逻辑（不连库、不读真实文件，输入用 str/dict/tmp_path 构造）。
不为了凑覆盖率——每个测试验证一个明确行为。
"""

import json
from pathlib import Path

import pytest

from check_sql import (
    read_sql, extract_from_tables, check_bracket_balance, check_no_select_star,
)
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


class TestNormalizeType:
    """归一化只处理「mapping 合法但 Gauss 非法」的带精度 int 家族；其余类型原样透传（mapping 是 source of truth）。"""

    def test_int8_with_precision(self):
        from assemble_ddl import normalize_type
        assert normalize_type("int8(64)") == "bigint"

    def test_int8_bare_passthrough(self):
        from assemble_ddl import normalize_type
        assert normalize_type("int8") == "int8"  # 裸 int8 Gauss 认，不动

    def test_int4_to_integer(self):
        from assemble_ddl import normalize_type
        assert normalize_type("int4(10)") == "integer"

    def test_varchar_kept(self):
        from assemble_ddl import normalize_type
        assert normalize_type("varchar(100)") == "varchar(100)"

    def test_case_insensitive(self):
        from assemble_ddl import normalize_type
        assert normalize_type("INT8(64)") == "bigint"

    def test_empty(self):
        from assemble_ddl import normalize_type
        assert normalize_type("") == ""

    def test_nvarchar_passthrough(self):
        from assemble_ddl import normalize_type
        assert normalize_type("nvarchar(50)") == "nvarchar(50)"
        assert normalize_type("nvarchar2(1)") == "nvarchar2(1)"  # 审计 del_flag 标准写法

    def test_varchar2_passthrough(self):
        from assemble_ddl import normalize_type
        assert normalize_type("varchar2(100)") == "varchar2(100)"

    def test_number_datetime_tinyint_passthrough(self):
        from assemble_ddl import normalize_type
        assert normalize_type("number(10,2)") == "number(10,2)"
        assert normalize_type("tinyint") == "tinyint"


class TestTimestampStandardWriting:
    """时间类型标准化书写（等价转换，不涉容量/语义）：datetime/裸 timestamp →
    timestamp(0) without time zone；显式精度保留只补全后缀；tz 系/date/time 不动。"""

    def test_datetime_to_standard(self):
        from assemble_ddl import normalize_type
        assert normalize_type("datetime") == "timestamp(0) without time zone"
        assert normalize_type("DATETIME") == "timestamp(0) without time zone"  # 大小写不敏感

    def test_bare_timestamp_gets_standard(self):
        from assemble_ddl import normalize_type
        assert normalize_type("timestamp") == "timestamp(0) without time zone"

    def test_explicit_precision_kept(self):
        from assemble_ddl import normalize_type
        assert normalize_type("timestamp(6)") == "timestamp(6) without time zone"

    def test_already_standard_idempotent(self):
        from assemble_ddl import normalize_type
        assert normalize_type("timestamp(0) without time zone") == "timestamp(0) without time zone"
        assert normalize_type("timestamp(3) without time zone") == "timestamp(3) without time zone"

    def test_tz_not_touched(self):
        """with time zone 存储语义不同（precheck 同名比对也视为不同类型），不标准化。"""
        from assemble_ddl import normalize_type
        assert normalize_type("timestamptz") == "timestamptz"
        assert normalize_type("timestamp(6) with time zone") == "timestamp(6) with time zone"

    def test_date_time_not_touched(self):
        from assemble_ddl import normalize_type
        assert normalize_type("date") == "date"
        assert normalize_type("time") == "time"


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
        """指定的 source 不在配置里 → raise（不静默换第一个数据源掩盖）。

        只走构造器配置校验不连库——dws_db 对 psycopg2 优雅降级，无需守卫。"""
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
        from dws_db import PsycopgExecutor
        cfg = tmp_path / "db-sources.json"
        cfg.write_text(json.dumps({
            "sources": {"src1": {"host": "h", "roles": {"etl": {"user": "u", "password": "p"}}}},
        }), encoding="utf-8")  # 无 default
        with pytest.raises(ValueError, match="未指定数据源"):
            PsycopgExecutor(str(cfg))  # 不传 source_name


# ============================================================
# config_paths.resolve_appid（appid 下多 schema，按 schema 反查所属 appid）
# ============================================================

class TestResolveAppid:
    def test_resolve_by_schema(self, tmp_path):
        """一个 appid 下多个 schema，按 schema 反查到所属 appid。"""
        from config_paths import resolve_appid
        cfg = tmp_path / "schema_apps.json"
        cfg.write_text(json.dumps({
            "default_appid": "DEFAULT_APP",
            "apps": {
                "SLPRD_APP": {"schemas": ["slprd", "slp", "md"]},
                "FIN_APP": {"schemas": ["fin", "fin_dim"]},
            },
        }), encoding="utf-8")
        assert resolve_appid("slprd", str(cfg)) == "SLPRD_APP"
        assert resolve_appid("fin_dim", str(cfg)) == "FIN_APP"  # 同 app 下另一个 schema

    def test_fallback_default(self, tmp_path):
        """schema 不属于任何 app → default_appid。"""
        from config_paths import resolve_appid
        cfg = tmp_path / "schema_apps.json"
        cfg.write_text(json.dumps({
            "default_appid": "DEFAULT_APP",
            "apps": {"FIN_APP": {"schemas": ["fin"]}},
        }), encoding="utf-8")
        assert resolve_appid("unknown_schema", str(cfg)) == "DEFAULT_APP"

    def test_missing_file_returns_empty(self, tmp_path):
        """文件不存在 → 空串（不阻断，调用方决定）。"""
        from config_paths import resolve_appid
        assert resolve_appid("slprd", str(tmp_path / "nope.json")) == ""


# ============================================================
# config_paths.opencode_root / config_dir（多候选探测 + 环境变量隔离）
# ============================================================

class TestOpencodeRoot:
    def test_config_dir_env_priority(self, tmp_path, monkeypatch):
        """环境变量 DWS_RULES_DIR 优先级最高——config_dir 直接返回它（不调 opencode_root）。"""
        from config_paths import config_dir
        monkeypatch.setenv("DWS_RULES_DIR", str(tmp_path))
        assert config_dir() == tmp_path

    def test_opencode_root_project_local(self, tmp_path, monkeypatch):
        """__file__ 推算 + 全局都 miss 时，cwd 向上找 .opencode 命中（项目级安装场景）。"""
        from config_paths import opencode_root, RULES_DIR_NAME
        # 构造项目级安装结构：<proj>/.opencode/_references/rules/dws-design-dev/
        proj = tmp_path / "myproj"
        (proj / ".opencode" / "_references" / "rules" / RULES_DIR_NAME).mkdir(parents=True)
        # 让全局探测 miss（home 指向 tmp 下空目录，避免命中机器真实全局 config）
        empty_home = tmp_path / "empty_home"
        empty_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: empty_home)
        monkeypatch.chdir(proj)
        assert opencode_root() == proj / ".opencode"

    def test_opencode_root_fallback_to_home_when_all_miss(self, tmp_path, monkeypatch):
        """全 miss（__file__/全局/项目级都没 marker）→ 回全局 home 路径（友好报错兜底）。"""
        from config_paths import opencode_root
        empty_home = tmp_path / "empty_home"
        empty_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: empty_home)
        monkeypatch.chdir(tmp_path)  # tmp 下没 .opencode，其祖先也不会有
        # 全 miss → 回全局 opencode 根（home/.config/opencode），保留旧行为兜底
        assert opencode_root() == empty_home / ".config" / "opencode"


# ============================================================
# dispatch_plan.build_dispatch_plan（执行计划：pipe 统一发起的依据）
# ============================================================

class TestDispatchPlan:
    def test_basic_plan(self):
        from dispatch_plan import build_dispatch_plan
        ts = {
            "rules": {
                "R0002": {"exec_sequence": 2},
                "R0001": {"exec_sequence": 1},
            },
            "init": {"mode": "derive", "rules": {"INIT_R0001": {}}},
            "dq_rules": [{"rule_name": "主键唯一"}],
            "data_flow": {"schedule_groups": [{"sequence": 1, "rules": ["R0001", "R0002"]}]},
        }
        plan = build_dispatch_plan(ts)
        assert plan["ddl"] is True
        assert plan["dq"] is True and plan["dq_count"] == 1
        assert plan["etl_rules"] == ["R0001", "R0002"]  # 按 exec_sequence 排序
        assert plan["init_rules"] == ["INIT_R0001"]
        assert len(plan["groups"]) == 1

    def test_no_dq_no_init(self):
        from dispatch_plan import build_dispatch_plan
        plan = build_dispatch_plan({"rules": {"R0001": {}}, "dq_rules": []})
        assert plan["dq"] is False
        assert plan["init_rules"] == []
        assert "无 DQ" in plan["summary"]


# ============================================================
# schema_query.query_fields（查缓存字段：designer/coder 公共能力）
# ============================================================

class TestSchemaQuery:
    @staticmethod
    def _make_cache(tmp_path, tables=None):
        import json as _json
        internal = tmp_path / "_internal"
        internal.mkdir(exist_ok=True)
        cache = {"tables": tables or {}, "cached_at": "2026-08-13T00:00:00"}
        (internal / "schema_cache.json").write_text(_json.dumps(cache), encoding="utf-8")
        return tmp_path / "ts.json"  # query_fields 只用 parent 定位 cache

    def test_no_cache_hints(self, tmp_path):
        """cache 不存在 → [未连库] 提示（不阻断）。"""
        from schema_query import query_fields
        out = query_fields(tmp_path / "ts.json", "ods", "ods_b")
        assert "未连库" in out

    def test_table_not_cached_lists_cached(self, tmp_path):
        """表不在缓存 → [未缓存] + 已缓存表清单。"""
        from schema_query import query_fields
        ts = self._make_cache(tmp_path, {"ods.ods_a": {"id": "bigint"}})
        out = query_fields(ts, "ods", "ods_b")
        assert "未缓存" in out and "ods.ods_a" in out

    def test_column_exists(self, tmp_path):
        """指定字段存在 → ✓ + 类型。"""
        from schema_query import query_fields
        ts = self._make_cache(tmp_path, {"ods.ods_b": {"col2": "varchar(50)", "id": "bigint"}})
        out = query_fields(ts, "ods", "ods_b", "col2")
        assert "存在" in out and "varchar(50)" in out

    def test_column_missing_lists_fields(self, tmp_path):
        """指定字段不存在 → ✗ + 全表字段帮对照。"""
        from schema_query import query_fields
        ts = self._make_cache(tmp_path, {"ods.ods_b": {"id": "bigint", "amt": "numeric"}})
        out = query_fields(ts, "ods", "ods_b", "nope")
        assert "不存在" in out and "amt" in out

    def test_list_all_fields(self, tmp_path):
        """不指定字段 → 全表字段清单。"""
        from schema_query import query_fields
        ts = self._make_cache(tmp_path, {"ods.ods_b": {"id": "bigint"}})
        out = query_fields(ts, "ods", "ods_b")
        assert "字段清单" in out and "id" in out

    def test_anchor_inside_internal(self, tmp_path):
        """锚点在 _internal/ 里（设计阶段传 rs_input.json）→ cache 与锚点同级也能定位。"""
        from schema_query import query_fields
        self._make_cache(tmp_path, {"ods.ods_b": {"col2": "varchar(50)"}})
        anchor = tmp_path / "_internal" / "rs_input.json"
        anchor.write_text("{}", encoding="utf-8")
        out = query_fields(anchor, "ods", "ods_b", "col2")
        assert "存在" in out and "varchar(50)" in out


class TestSqlParseCtePrimitives:
    """CTE 体解析/投影提取/原始表引用（check_sql 的 schema 与 CTE 一致性校验的原语）。"""

    def test_parse_cte_bodies(self):
        from sql_parse import parse_cte_bodies
        sql = ("WITH a AS (SELECT t.x FROM ods.f1 t), b AS (SELECT a.x FROM a) "
               "SELECT b.x FROM b")
        bodies = parse_cte_bodies(sql)
        assert set(bodies) == {"a", "b"}
        assert "ods.f1" in bodies["a"]

    def test_parse_cte_bodies_no_with(self):
        from sql_parse import parse_cte_bodies
        assert parse_cte_bodies("SELECT 1") == {}

    def test_cte_projection_names(self):
        from sql_parse import cte_projection_names
        body = "SELECT t.a, t.b AS bb, count(*) AS cnt FROM ods.f t GROUP BY t.a, t.b"
        names = cte_projection_names(body)
        assert {"a", "bb", "cnt"} <= names  # 裸引用列名 + AS 别名都收（宁多勿漏）

    def test_extract_table_refs_raw(self):
        from sql_parse import extract_table_refs_raw
        sql = "FROM ods.a_f t LEFT JOIN b_f m ON t.id = m.id"
        assert extract_table_refs_raw(sql) == ["ods.a_f", "b_f"]


class TestSqlParseStringAwareness:
    """括号深度扫描的字符串字面量感知（修 CTE 边界错位→INSERT 列重复的根因）。"""

    def test_string_paren_does_not_break_cte_boundary(self):
        from sql_parse import split_cte_main, extract_select_aliases
        sql = ("WITH base AS (SELECT t.id, t.remark AS remark FROM ods.a_f t "
               "WHERE t.note = '(') "
               "SELECT base.id AS id, base.remark AS remark FROM base")
        names, main = split_cte_main(sql)
        assert names == ["base"]
        assert main.startswith("SELECT base.id")
        assert extract_select_aliases(sql) == ["id", "remark"]  # CTE 内别名不泄漏

    def test_parse_cte_bodies_string_aware(self):
        from sql_parse import parse_cte_bodies
        sql = "WITH b AS (SELECT x FROM t WHERE s = ')') SELECT b.x AS x FROM b"
        bodies = parse_cte_bodies(sql)
        assert set(bodies) == {"b"} and "s = ')'" in bodies["b"]
        assert bodies["b"].endswith("FROM t WHERE s = ')'") or "FROM t" in bodies["b"]

    def test_insert_columns_duplicate_raises(self):
        from run_ut import _resolve_insert_columns
        import pytest
        dup_sql = "WITH b AS (SELECT x AS id FROM t) SELECT b.id AS id, b.id AS id2 FROM b"
        # 手工构造重复别名场景（解析器正常但 SELECT 真重复输出）
        with pytest.raises(ValueError, match="重复列"):
            _resolve_insert_columns("SELECT a AS x, b AS x FROM t", [])


class TestCastTypeStripping:
    """CAST(x AS <type>) 结构化剥除——类型名是开放集（int8/timestamptz…），枚举白名单必漏。

    曾经：int8 不在 ANSI 白名单 → 泄漏成输出列 → wrap_insert 拼出假列 → UT COLUMN 错
    回 coder（他的 SQL 本身没错，改不动）→ 自写脚本修 → 越修越坏。
    """

    def test_gaussdb_type_names_not_leaked_as_alias(self):
        from sql_parse import extract_select_aliases
        sql = "SELECT CAST(a.amt AS int8) AS amt2, CAST(a.dt AS timestamptz) FROM sch.t a"
        assert extract_select_aliases(sql) == ["amt2"]

    def test_two_int8_casts_no_duplicate_column_error(self):
        # 两个 CAST AS int8 曾触发重复列报错（文案指向 CTE 边界，误导 coder）
        from run_ut import _resolve_insert_columns
        sql = ("WITH c AS (SELECT 1 AS k) "
               "SELECT CAST(a.k AS int8) AS k2, CAST(2 AS int8) AS j2 FROM t a")
        assert _resolve_insert_columns(sql, []) == ["k2", "j2"]

    def test_precision_and_nested(self):
        from sql_parse import extract_select_aliases
        assert extract_select_aliases(
            "SELECT CAST(a.amt AS numeric(18,2)) FROM t a") == []
        assert extract_select_aliases(
            "SELECT CAST(CAST(a.amt AS int4) AS varchar) FROM t a") == []

    def test_string_literal_with_as_inside_cast(self):
        from sql_parse import extract_select_aliases
        sql = "SELECT CAST(a.r || ' AS int8' AS varchar(100)) AS r2 FROM t a"
        assert extract_select_aliases(sql) == ["r2"]

    def test_try_cast_and_comment_with_paren(self):
        from sql_parse import extract_select_aliases
        assert extract_select_aliases(
            "SELECT TRY_CAST(a.amt AS decimal(10,2)) FROM t a") == []
        assert extract_select_aliases(
            "SELECT CAST(a.amt /* ) */ AS int8) AS v FROM t a") == ["v"]

    def test_subquery_alias_inside_cast_preserved(self):
        # CAST 内子查询里的真别名（深度>1）不被剥；类型名（深度0的 AS）不泄漏
        from sql_parse import extract_select_aliases
        aliases = extract_select_aliases(
            "SELECT CAST((SELECT max(x) AS mx FROM u) AS int8) AS v FROM t")
        assert "v" in aliases and "int8" not in aliases

    def test_dollar_brace_param_untouched(self):
        from sql_parse import extract_select_aliases
        sql = "SELECT CAST(${v} AS int8) AS x FROM t WHERE dt = ${bdp.system.bizdate}"
        assert extract_select_aliases(sql) == ["x"]

    def test_colon_cast_with_precision(self):
        from sql_parse import extract_select_aliases
        assert extract_select_aliases(
            "SELECT a.amt::numeric(18,2) AS amt2 FROM t") == ["amt2"]

    def test_unbalanced_parens_degrades_gracefully(self):
        # 烂 SQL（括号不平衡）：结构剥除放弃、白名单兜底，不抛异常
        from sql_parse import extract_select_aliases
        assert extract_select_aliases("SELECT CAST(a.amt AS varchar FROM t") == []
        # int8 不在白名单 → 降级后泄漏（文档化的降级行为，宁放过不误报）
        assert extract_select_aliases("SELECT CAST(a.amt AS int8 FROM t") == ["int8"]


class TestRunDqChecks:
    """DQ 检查执行（run_dq_checks）：契约 = 违规行探测器——0 行通过，非 0 行告警。

    行数用 COUNT 包裹判（不拉全量结果集），告警才追加 LIMIT 采样；
    文件按 dq_rules.check_type 确定名拼接，缺失即 MISSING。
    """

    class _Exec:
        """按 SQL 片段返回预置行数的 fake executor。count_map: 片段→cnt。"""

        def __init__(self, count_map=None, error_sub=None):
            self.count_map = count_map or {}
            self.error_sub = error_sub
            self.executed = []

        def execute(self, sql):
            self.executed.append(sql)

            class _R:
                def __init__(self, success, rows=None, error=""):
                    self.success = success
                    self.rows = rows or []
                    self.error = error
            if self.error_sub and self.error_sub in sql:
                return _R(False, error="COLUMN does not exist: bad_col")
            if "COUNT(*)" in sql:
                cnt = next((c for frag, c in self.count_map.items() if frag in sql), 0)
                return _R(True, rows=[{"cnt": cnt}])
            # 采样查询（LIMIT 5）
            return _R(True, rows=[{"order_no": "O1", "amt": None}, {"order_no": "O2", "amt": None}])

    @staticmethod
    def _rules(**kw):
        base = {"check_type": "空值检查", "rule_name": "金额非空"}
        base.update(kw)
        return [base]

    def test_zero_rows_passes_without_sample_query(self, tmp_path):
        from run_ut import run_dq_checks
        (tmp_path / "dq_空值检查.sql").write_text(
            "/* 检查空值 */\nSELECT order_no, amt FROM dws.t WHERE amt IS NULL;", encoding="utf-8")
        ex = self._Exec()
        results = run_dq_checks(ex, tmp_path, self._rules(), {})
        assert results[0]["status"] == "PASS" and results[0]["rows"] == 0
        assert len(ex.executed) == 1  # 0 行不做采样查询
        assert "COUNT(*)" in ex.executed[0]  # COUNT 包裹判行数
        assert ex.executed[0].startswith("SELECT COUNT(*)")  # 注释已被 read_sql 剥掉

    def test_nonzero_rows_alert_with_samples(self, tmp_path):
        from run_ut import run_dq_checks
        (tmp_path / "dq_空值检查.sql").write_text(
            "SELECT order_no, amt FROM dws.t WHERE amt IS NULL", encoding="utf-8")
        ex = self._Exec(count_map={"amt IS NULL": 3})
        results = run_dq_checks(ex, tmp_path, self._rules(), {})
        r = results[0]
        assert r["status"] == "ALERT" and r["rows"] == 3 and "3 行违规" in r["detail"]
        assert r["samples"] and "O1" in r["samples"][0]
        assert any("LIMIT 5" in s for s in ex.executed)  # 告警才采样

    def test_exec_error_fails(self, tmp_path):
        from run_ut import run_dq_checks
        (tmp_path / "dq_空值检查.sql").write_text(
            "SELECT bad_col FROM dws.t WHERE bad_col IS NULL", encoding="utf-8")
        results = run_dq_checks(self._Exec(error_sub="bad_col"), tmp_path, self._rules(), {})
        assert results[0]["status"] == "FAIL" and "bad_col" in results[0]["detail"]

    def test_missing_file_reported(self, tmp_path):
        from run_ut import run_dq_checks
        results = run_dq_checks(self._Exec(), tmp_path, self._rules(), {})
        assert results[0]["status"] == "MISSING" and "dq_空值检查.sql" in results[0]["detail"]

    def test_param_substituted_and_missing_param_fails(self, tmp_path):
        from run_ut import run_dq_checks
        (tmp_path / "dq_空值检查.sql").write_text(
            "SELECT order_no FROM dws.t WHERE dt < ${P_CYCLE_ID}", encoding="utf-8")
        ex = self._Exec()
        run_dq_checks(ex, tmp_path, self._rules(), {"P_CYCLE_ID": "20260826"})
        assert all("${" not in s for s in ex.executed) and "20260826" in ex.executed[0]
        results = run_dq_checks(self._Exec(), tmp_path, self._rules(), {})  # 没配测试值
        assert results[0]["status"] == "FAIL" and "P_CYCLE_ID" in results[0]["detail"]


class TestLogicRefs:
    """口径引用骨架提取（extract_logic_refs/diff_logic_refs）——翻译对账的机器原料。

    真实案例：del_flag 口径伪代码引用三字段（a.del_flag/delete_flag/u.del_flag），
    mapping 源字段单元格只写一个——加工字段的真来源活在口径里，引用集可结构提取。
    """

    def test_qualified_and_bare_extraction(self):
        from sql_parse import extract_logic_refs
        reg = {"del_flag", "delete_flag", "amt"}
        q, b = extract_logic_refs("当 a.del_flag 和 delete_flag 以及 u.del_flag 都为 n 或空", reg)
        assert q == [("a", "del_flag"), ("u", "del_flag")]
        assert b == ["delete_flag"]  # 裸 token 命中登记处

    def test_noise_words_and_params_excluded(self):
        from sql_parse import extract_logic_refs
        q, b = extract_logic_refs(
            "CASE WHEN x=1 THEN sum(amt) ELSE null END，dt<${P_CYCLE_ID} 取 N", {"amt", "dt", "x"})
        assert q == []
        assert "amt" in b and "dt" in b  # 列名命中
        assert all(w not in b for w in ("case", "when", "sum", "null", "end", "then"))  # 噪音词不进
        # 未命中登记处的英文词不管（中文/数字天然不参与）

    def test_find_unqualified_refs_pure_syntax(self):
        """N36 守门原语：纯语法零漏报（不依赖登记处）——限定/引号/${}/函数/类型词/单字母豁免。"""
        from sql_parse import find_unqualified_refs
        assert find_unqualified_refs("a.del_flag、u.delete_flag 均为 N 或空") == []
        assert find_unqualified_refs("a.del_flag 和 delete_flag 为 N") == ["delete_flag"]
        # 引号串（值）、${参数}、函数调用、SQL 类型词不参与
        assert find_unqualified_refs(
            "CASE WHEN x=1 THEN 'Y' ELSE 'N' END，cast(amt as int8)，dt<${P}") == ["amt", "dt"]
        assert find_unqualified_refs("返回 n 否则 y") == []  # 单字母豁免
        assert find_unqualified_refs("按 coalesce(x, 0) 与 to_char(a.dt,'yyyymmdd') 处理") == []

    def test_diff_detects_dropped_reference(self):
        from sql_parse import diff_logic_refs
        # 原文引用集是实例形态（与 view refs 同粒度），diff 投影到列名比较
        assert diff_logic_refs(["a.del_flag", "u.del_flag", "delete_flag"],
                               ["a.del_flag、u.delete_flag、u.del_flag 均为 N 或空 → N"]) == []
        # 翻译丢了 delete_flag → 对账抓到（真实案例形态）
        assert diff_logic_refs(["a.del_flag", "u.del_flag", "delete_flag"],
                               ["a.del_flag 为 N 或空 → N"]) == ["delete_flag"]


class TestViewCommentSyntax:
    """视图 DDL 的对象注释必须是 COMMENT ON VIEW（GaussDB 语法；TABLE 会报错）。"""

    def test_generate_i_view_uses_comment_on_view(self):
        from assemble_ddl import generate_i_view
        fields = [{"target_field": "id", "field_comment": "ID"}]
        out = generate_i_view("dws", "dwb_x_f", "宽表", fields, {})
        assert "COMMENT ON VIEW dws.dwb_x_i" in out
        assert "COMMENT ON TABLE" not in out

    def test_create_table_keeps_comment_on_table(self):
        from assemble_ddl import generate_create_table
        rule = {"target_table": "dws.dwb_x_f", "rule_name": "宽表"}
        meta = {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"}}}
        tables = {"dwb_x_f": {"fields": [{"target_field": "id", "field_type": "bigint",
                                          "field_comment": "ID"}],
                              "distribution_key": ["id"], "distribute_type": "HASH",
                              "logical_group": "", "partition": "", "storage": "column"}}
        out = generate_create_table("R0001", rule, {}, meta, tables)
        assert "COMMENT ON TABLE dws.dwb_x_f" in out


class TestDeployAllDdl:
    """ut_precheck 统一 DDL 部署：回退容忍（先视图后表）→ 建表（失败收集）→ I 视图（容忍）。"""

    class _Exec:
        def __init__(self, fail_tables=()):
            self.executed = []
            self.fail_tables = set(fail_tables)

        def execute(self, sql):
            self.executed.append(sql)
            class _R:
                def __init__(self, ok):
                    self.success = ok
                    self.error = "" if ok else "boom"
                def summary(self):
                    return "ok" if self.success else "boom"
            import re as _r
            m = _r.search(r"create_table_(\w+)", sql)
            ok = not (m and m.group(1) in self.fail_tables)
            return _R(ok)

    def _files(self, tmp_path, tables, i_view="dwb_x_i"):
        # 内容自带标记（执行器按内容判失败，文件名只是部署侧拼接）
        for tb in tables:
            (tmp_path / f"create_table_{tb}.sql").write_text(f"create_table_{tb}", encoding="utf-8")
            (tmp_path / f"rollback_create_table_{tb}.sql").write_text(f"rollback_table_{tb}", encoding="utf-8")
        (tmp_path / f"create_view_{i_view}.sql").write_text("create_view_x", encoding="utf-8")
        (tmp_path / f"rollback_create_view_{i_view}.sql").write_text("rollback_view", encoding="utf-8")

    def test_rollback_view_first_then_tables_then_create(self, tmp_path):
        from ut_precheck import _deploy_all_ddl
        self._files(tmp_path, ["tmp1", "dwb_x_f"])
        ex = self._Exec()
        errors = _deploy_all_ddl(ex, tmp_path, tmp_path, {"tmp1", "dwb_x_f"}, "dwb_x_i", {})
        assert errors == []
        # 顺序：回退视图 → 回退表(字典序) → 建表(字典序) → 建视图
        assert ex.executed[0] == "rollback_view"
        assert ex.executed[1] == "rollback_table_dwb_x_f" and ex.executed[2] == "rollback_table_tmp1"
        assert ex.executed[3] == "create_table_dwb_x_f" and ex.executed[4] == "create_table_tmp1"
        assert ex.executed[-1] == "create_view_x"

    def test_create_table_failure_collected(self, tmp_path):
        from ut_precheck import _deploy_all_ddl
        self._files(tmp_path, ["tmp1", "dwb_x_f"])
        ex = self._Exec(fail_tables={"tmp1"})
        errors = _deploy_all_ddl(ex, tmp_path, tmp_path, {"tmp1", "dwb_x_f"}, "dwb_x_i", {})
        assert len(errors) == 1 and errors[0].startswith("tmp1")

    def test_view_create_failure_collected(self, tmp_path):
        """部署必须全绿：I 视图建失败同样收集（UT 建不成=生产问题，不容忍）。"""
        from ut_precheck import _deploy_all_ddl
        self._files(tmp_path, ["dwb_x_f"])

        class _ExecViewFail(self._Exec):
            def execute(self, sql):
                r = super().execute(sql)
                if sql.startswith("create_view"):
                    r.success = False
                    r.error = "view boom"
                return r

        errors = _deploy_all_ddl(_ExecViewFail(), tmp_path, tmp_path, {"dwb_x_f"}, "dwb_x_i", {})
        assert len(errors) == 1 and errors[0].startswith("view_dwb_x_i")

    def test_rollback_failure_tolerated(self, tmp_path):
        """回退失败不阻断（首次无对象）：建表照常执行且成功。"""
        from ut_precheck import _deploy_all_ddl
        self._files(tmp_path, ["dwb_x_f"])
        ex = self._Exec(fail_tables=set())  # 回退由同一 execute 跑——构造回退失败需按内容判
        # 用一个对回退 SQL 报错的执行器
        class _ExecRbFail(self._Exec):
            def execute(self, sql):
                r = super().execute(sql)
                if sql.startswith("rollback"):
                    r.success = False
                    r.error = "first run no object"
                return r
        ex = _ExecRbFail()
        errors = _deploy_all_ddl(ex, tmp_path, tmp_path, {"dwb_x_f"}, "dwb_x_i", {})
        assert errors == []  # 回退失败被容忍，建表成功


