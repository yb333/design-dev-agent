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
                "R0002": {"exec_sequence": 2, "is_view_step": False},
                "R0001": {"exec_sequence": 1, "is_view_step": False},
                "V0001": {"exec_sequence": 3, "is_view_step": True},  # 视图步骤，排除
            },
            "init": {"mode": "derive", "rules": {"INIT_R0001": {}}},
            "dq_rules": [{"rule_name": "主键唯一"}],
            "data_flow": {"schedule_groups": [{"sequence": 1, "rules": ["R0001", "R0002"]}]},
        }
        plan = build_dispatch_plan(ts)
        assert plan["ddl"] is True
        assert plan["dq"] is True and plan["dq_count"] == 1
        assert plan["etl_rules"] == ["R0001", "R0002"]  # 按 exec_sequence 排序 + 排除视图
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


class TestViewCommentSyntax:
    """视图 DDL 的对象注释必须是 COMMENT ON VIEW（GaussDB 语法；TABLE 会报错）。"""

    def test_generate_i_view_uses_comment_on_view(self):
        from assemble_ddl import generate_i_view
        fields = [{"target_field": "id", "field_comment": "ID"}]
        out = generate_i_view("dws", "dwb_x_f", "宽表", fields, {})
        assert "COMMENT ON VIEW dws.dwb_x_i" in out
        assert "COMMENT ON TABLE" not in out

    def test_generate_create_view_uses_comment_on_view(self):
        from assemble_ddl import generate_create_view
        rule = {"target_table": "dws.dwb_x_i", "rule_name": "宽表视图"}
        meta = {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"},
                           "i_view": {"schema": "dws", "table": "dwb_x_i"},
                           "f_table_cn": "宽表"}}
        tables = {"dwb_x_f": {"fields": [{"target_field": "id", "field_comment": "ID"}]}}
        out = generate_create_view("R0002", rule, meta, {}, tables)
        assert "COMMENT ON VIEW" in out
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


class TestDeployIView:
    """ut_precheck 的 I 视图部署：先回退再建；文件缺失返回 None 跳过。"""

    class _Exec:
        def __init__(self):
            self.executed = []

        def execute(self, sql):
            self.executed.append(sql)
            class _R:
                success = True
                def summary(self):
                    return "ok"
            return _R()

    def test_deploy_runs_rollback_then_create(self, tmp_path):
        from ut_precheck import _deploy_i_view
        (tmp_path / "rollback_create_view_dwb_x_i.sql").write_text("-- rb", encoding="utf-8")
        (tmp_path / "create_view_dwb_x_i.sql").write_text("CREATE VIEW ...", encoding="utf-8")
        ex = self._Exec()
        r = _deploy_i_view(ex, tmp_path, tmp_path, "dwb_x_i", {})
        assert r is not None and r.success
        assert ex.executed == ["-- rb", "CREATE VIEW ..."]

    def test_missing_files_skip(self, tmp_path):
        from ut_precheck import _deploy_i_view
        ex = self._Exec()
        assert _deploy_i_view(ex, tmp_path, tmp_path, "ghost_i", {}) is None
        assert ex.executed == []
