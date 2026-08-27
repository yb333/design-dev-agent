"""
precheck 的 DB 校验测试（_check_db_schema）。

用 mock executor 模拟连库场景，验证：
1. 连不上库 → 静默跳过（不阻断，不报 error）
2. 表不存在 → error（阻断）
3. 字段不存在 → error（阻断）
4. 全部存在 → pass，无 error
5. 纯派生行（赋值/序列、source_column 空）跳过，不查源表
6. 审计字段跳过，不查源表

不连真库——通过 monkeypatch 替换 create_executor_for_schema。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# conftest 已把 design-dev-shared/scripts 加入 sys.path
from precheck import precheck, PrecheckResult


# ============================================================
# 辅助：构造 rs_input
# ============================================================

def _make_rs_input(fields, sources=None, schema="ods", table="ods_test_f"):
    """构造最小 rs_input，target_schema 故意设为 dws（与源表 ods 不同）。"""
    if sources is None:
        sources = [{"source_schema": schema, "source_table": table,
                    "source_table_cn": "测试源表", "source_alias": "t",
                    "target_schema": "dws", "target_table": "dwb_test_i"}]
    return {
        "meta": {
            "target": {
                "f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试"},
                "i_view": {"schema": "dws", "table": "dwb_test_i", "cn": "测试"},
            },
        },
        "source_tables": sources,
        "field_mappings": fields,
        "schedule": {"frequency": "T+1", "upstream": []},
    }


def _biz_field(source_column="id", target_column="id", rule="直接复制"):
    """构造一个业务字段映射行。"""
    # 数据加工必须有合法的映射表达式（非"-"），否则静态检查报 error
    detail = "SUM(amount)" if rule == "数据加工" else "-"
    return {
        "source_schema": "ods", "source_table": "ods_test_f",
        "source_column": source_column, "source_type": "VARCHAR(64)",
        "transform_rule": rule, "transform_detail": detail,
        "target_column": target_column, "target_column_cn": target_column,
        "target_type": "VARCHAR(64)", "source_alias": "t",
    }


def _audit_field(target_column="del_flag"):
    """构造一个审计字段（赋值，无 source_column）。"""
    return {
        "transform_rule": "赋值", "transform_detail": "'N'",
        "target_column": target_column, "target_column_cn": "删除标识",
        "target_type": "NVARCHAR(1)", "remark": "审计字段",
    }


def _make_mock_executor(table_columns: dict, conn_status=None):
    """构造 mock executor。

    table_columns 支持两种格式：
      {(schema, table): [col1, col2]} —— 只给列名，类型默认 "varchar"
      {(schema, table): {col1: type1, col2: type2}} —— 列名+类型
    conn_status: 连接诊断结果（dws_db.ConnectionStatus），默认 None=连接正常。
                 测密码错/连不上时传 ConnectionStatus(ok=False, category=...)。
    适配 UNION ALL 批量查询：返回带 nsp/rel/col/col_type 的行。
    """
    from dws_db import ConnectionStatus
    if conn_status is None:
        conn_status = ConnectionStatus(ok=True)
    executor = MagicMock()
    executor.diagnose_connection.return_value = conn_status
    executor.test_connection.return_value = conn_status.ok  # 向后兼容

    def fake_execute(sql):
        result = MagicMock()
        result.success = True
        result.error = ""
        rows = []
        for (sch, tbl), cols_def in table_columns.items():
            sch_l = sch.lower()
            tbl_l = tbl.lower()
            if f"'{sch_l}' AS nsp" in sql and f"'{tbl_l}' AS rel" in sql:
                # 兼容 list（无类型）和 dict（有类型）
                if isinstance(cols_def, dict):
                    for c, t in cols_def.items():
                        rows.append({"nsp": sch_l, "rel": tbl_l, "col": c, "col_type": t or "character varying(64)"})
                else:
                    for c in cols_def:
                        rows.append({"nsp": sch_l, "rel": tbl_l, "col": c, "col_type": "character varying(64)"})
        result.rows = rows
        return result

    executor.execute.side_effect = fake_execute
    return executor


# ============================================================
# 测试用例
# ============================================================

class TestCheckDbSchema:
    """DB 校验逻辑测试。"""

    def test_no_db_driver_warns(self, monkeypatch):
        """数据库驱动缺失（psycopg2 未装，ImportError）= 环境问题 → warn 跳过，不阻断。"""
        def boom(schema, config_path=""):
            raise ImportError("psycopg2 未安装")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        # ImportError 是环境问题 → warn，不是 error（不阻断）
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e or "DB配置错误" in e)]
        assert db_errors == [], f"驱动缺失不应报 DB error: {db_errors}"
        # 应有 warn 告知（不静默）
        assert any("驱动缺失" in w or "DB校验跳过" in w for w in result.warnings), \
            f"驱动缺失应 warn 告知: {result.warnings}"

    def test_server_unreachable_warns(self, monkeypatch):
        """服务器连不上（server_unreachable）= 环境不可用 → warn 跳过，不阻断。"""
        from dws_db import ConnectionStatus
        executor = _make_mock_executor(
            {},
            conn_status=ConnectionStatus(ok=False, category="server_unreachable",
                                         reason="could not connect to server: Connection refused"),
        )
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        # 环境不可用 → warn，不报 error（不阻断）
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e or "DB" in e)]
        assert db_errors == [], f"服务器连不上不应报 error: {db_errors}"
        assert any("DB校验跳过" in w or "连不上" in w for w in result.warnings), \
            f"服务器连不上应 warn 告知原因: {result.warnings}"

    def test_auth_failed_blocks(self, monkeypatch):
        """密码错（auth_failed）= 配置错误 → error 阻断（不掩盖）。"""
        from dws_db import ConnectionStatus
        executor = _make_mock_executor(
            {},
            conn_status=ConnectionStatus(ok=False, category="auth_failed",
                                         reason='password authentication failed for user "etl"'),
        )
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        # 密码错 = 配置错误 → error 阻断
        auth_errors = [e for e in result.errors if "DB连接失败" in e and "配置错误" in e]
        assert auth_errors, f"密码错应报 [DB连接失败·配置错误] error: {result.errors}"
        assert "password authentication" in auth_errors[0] or "密码" in auth_errors[0]

    def test_db_not_found_blocks(self, monkeypatch):
        """库名错（db_not_found）= 配置错误 → error 阻断。"""
        from dws_db import ConnectionStatus
        executor = _make_mock_executor(
            {},
            conn_status=ConnectionStatus(ok=False, category="db_not_found",
                                         reason='FATAL: database "xxx" does not exist'),
        )
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        db_errs = [e for e in result.errors if "DB连接失败" in e and "配置错误" in e]
        assert db_errs, f"库名错应报 error: {result.errors}"

    def test_schema_mapping_missing_blocks(self, monkeypatch):
        """schema 没配 schema_mapping = 配置错误 → error 阻断（不再静默回退 default）。"""
        def boom(schema, config_path=""):
            raise ValueError(f"schema '{schema}' 不在 schema_mapping 配置里")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        cfg_errors = [e for e in result.errors if "DB配置错误" in e and "schema_mapping" in e]
        assert cfg_errors, f"schema_mapping 缺应报 [DB配置错误]: {result.errors}"

    def test_table_not_exists_blocks(self, monkeypatch):
        """表在库里不存在 → 它的字段全部查不到，报字段不存在（阻断）。

        新逻辑不单独查表存在性：表不存在 = 用到的字段全查不到，统一报字段不存在。
        """
        executor = _make_mock_executor({})  # 空字典 = 库里没这张表的任何列
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert any("id" in e and "不存在" in e for e in db_errors), \
            f"表不存在时其字段应报不存在: {db_errors}"
        # 阻断：return_code 应为 2
        assert result.return_code == 2

    def test_column_not_exists_blocks(self, monkeypatch):
        """字段在表里不存在 → error（阻断）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id", "name", "amount"]  # 没有 not_exist_col
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="not_exist_col",
                                        target_column="bad_field")])
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert any("not_exist_col" in e and "不存在" in e for e in db_errors), \
            f"字段不存在应报 error: {db_errors}"
        assert result.return_code == 2

    def test_all_exist_passes(self, monkeypatch):
        """表和字段都在库里 → 无 DB error。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id", "name", "amount"]
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([
            _biz_field(source_column="id", target_column="id"),
            _biz_field(source_column="amount", target_column="total",
                       rule="数据加工"),
        ])
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"全部存在不应报 error: {db_errors}"
        # 应有 DB 校验通过的 pass（含表数/字段数）
        db_passes = [p for p in result.passed if "DB 校验" in p]
        assert len(db_passes) >= 1
        assert "字段" in db_passes[0]  # pass 文案应含字段数

    def test_case_insensitive_column_match(self, monkeypatch):
        """列名大小写不敏感（库是 ID，mapping 是 id）→ 匹配成功。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["ID", "NAME"]  # 大写
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])  # 小写
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"大小写不敏感应匹配: {db_errors}"

    def test_audit_field_not_checked(self, monkeypatch):
        """审计字段（赋值、source_column 空）不查源表。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id"]  # 只有 id
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([
            _biz_field(source_column="id"),
            _audit_field("del_flag"),  # 审计字段，source_column 为空
        ])
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"审计字段不应被校验: {db_errors}"

    def test_derived_field_not_checked(self, monkeypatch):
        """纯派生行（赋值类，有 target 但无 source_column）不查源表。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id"]
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        # 一个业务字段 + 一个赋值字段（source_column 空）
        derived = {
            "transform_rule": "赋值", "transform_detail": "'ACTIVE'",
            "target_column": "status", "target_column_cn": "状态",
            "target_type": "VARCHAR(16)", "remark": "",
        }
        rs = _make_rs_input([_biz_field(source_column="id"), derived])
        result = precheck(rs)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"纯派生字段不应被校验: {db_errors}"

    def test_assign_field_with_placeholder_not_checked(self, monkeypatch):
        """赋值字段 source_column 是占位符（-、/ 等）也不查源表。

        BA 写赋值字段时 mapping 可能填 source_column='-'，preprocess 解析进去后
        不该拿 '-' 去库里查（必然报字段不存在）。
        """
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id"]
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        # 赋值字段，source_column 填了占位符 '-'
        assign_placeholder = {
            "transform_rule": "赋值", "transform_detail": "NULL AS status",
            "target_column": "status", "target_column_cn": "状态",
            "target_type": "VARCHAR(2)", "source_column": "-",
            "source_schema": "-", "source_table": "-", "source_alias": "",
            "remark": "",
        }
        rs = _make_rs_input([_biz_field(source_column="id"), assign_placeholder])
        result = precheck(rs)
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"赋值字段占位符不该查库: {db_errors}"

    def test_field_not_exist_vs_type_mismatch_distinct(self, monkeypatch):
        """字段不存在 vs 类型不符 是两种不同错误，报错文案应明确区分。"""
        # 场景1：字段在库里不存在 → [字段不存在] 标记
        executor1 = _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor1)
        rs1 = _make_rs_input([
            _biz_field(source_column="ghost_col"),  # 库里没有这列
        ])
        result1 = precheck(rs1)
        not_exist_errs = [e for e in result1.errors if "[字段不存在]" in e]
        assert any("ghost_col" in e for e in not_exist_errs), \
            f"字段不存在应有[字段不存在]标记: {result1.errors}"

        # 场景2：字段存在但类型不符 → [类型不符] 标记
        executor2 = _make_mock_executor({("ods", "ods_test_f"): {"id": "varchar(50)"}})
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor2)
        rs2 = _make_rs_input([_biz_field(source_column="id")])  # mapping 标 bigint，库是 varchar
        result2 = precheck(rs2)
        type_errs = [e for e in result2.errors if "[类型不符]" in e]
        assert type_errs, f"类型不符应有[类型不符]标记: {result2.errors}"

    def test_union_all_batch_query(self, monkeypatch):
        """连库查表结构用 UNION ALL（实测 DWS 最快），走 pg_catalog 精确表名。

        表里有 id/name/amount/extra_col 四个字段，mapping 只用了 id。
        查的是整表列（不再 attname IN），比对在 Python 端做。
        """
        captured_sql = []
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): ["id", "name", "amount", "extra_col"]
        })
        # 拦截 SQL
        orig_execute = executor.execute.side_effect
        def capture_execute(sql):
            captured_sql.append(sql)
            return orig_execute(sql)
        executor.execute.side_effect = capture_execute
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        assert captured_sql, "应有查询执行"
        sql_text = captured_sql[0]
        # SQL 应走 pg_catalog（不用慢的 information_schema）
        assert "pg_attribute" in sql_text, f"应用 pg_catalog 系统表，实际: {sql_text}"
        assert "information_schema" not in sql_text, "不应再用 information_schema（慢）"
        # 带 schema/table 标记列（UNION ALL 形式）
        assert "AS nsp" in sql_text and "AS rel" in sql_text, \
            f"UNION ALL 应带 nsp/rel 标记列: {sql_text}"
        # 精确表名（每个分支 WHERE c.relname=）
        assert "c.relname = 'ods_test_f'" in sql_text, f"应精确表名: {sql_text}"
        # 校验通过（id 确实存在）
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == []

    def test_static_error_skips_db_check(self, monkeypatch):
        """静态检查有 error 时，不进 DB 校验（短路，避免白白连库）。

        构造一个静态就报 error 的 rs_input（目标字段重复），
        验证 create_executor_for_schema 根本没被调用。
        """
        executor_called = {"n": 0}
        def tracking_executor(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking_executor)

        # 两个字段 target_column 相同 → 静态检查报 error（字段重复）
        rs = _make_rs_input([
            _biz_field(source_column="id", target_column="dup_field"),
            _biz_field(source_column="name", target_column="dup_field"),
        ])
        result = precheck(rs)

        # 静态应有 error（字段重复）
        assert any("重复" in e for e in result.errors), \
            f"应报字段重复 error: {result.errors}"
        # DB 校验不应执行（短路）
        assert executor_called["n"] == 0, \
            f"静态有 error 时不应连库，实际连了 {executor_called['n']} 次"

    def test_static_warning_still_runs_db_check(self, monkeypatch):
        """静态检查只有 warning（无 error）时，仍进 DB 校验（告警不阻断）。"""
        executor_called = {"n": 0}
        def tracking_executor(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking_executor)

        # 正常字段（无静态 error），schedule.upstream 空 → 触发 warning（不是 error）
        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        # 有 warning（上游调度缺失）但无 error
        assert result.warnings, "应有 warning"
        assert not result.errors, f"不应有 error: {result.errors}"
        # DB 校验应执行（warning 不阻断）
        assert executor_called["n"] == 1, \
            f"只有 warning 时应照常连库，实际连了 {executor_called['n']} 次"


class TestSchemaCache:
    """表结构缓存测试：命中优先，过期/缺失才连库。"""

    def test_cache_hit_no_db_connection(self, tmp_path, monkeypatch):
        """缓存命中（未过期）→ 不连库，纯本地对比。"""
        cache_path = tmp_path / "schema_cache.json"
        # 预置缓存：ods.ods_test_f 有 id 列
        import json
        cache_path.write_text(json.dumps({
            "cached_at": "2099-01-01T00:00:00",  # 未来时间，未过期
            "tables": {"ods.ods_test_f": ["id", "name"]},
        }), encoding="utf-8")

        # executor 不应被调用
        executor_called = {"n": 0}
        def boom(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, cache_path)

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"缓存命中应校验通过: {db_errors}"
        assert executor_called["n"] == 0, "缓存命中不应连库"

    def test_cache_miss_fetches_from_db(self, tmp_path, monkeypatch):
        """缓存过期/不存在 → 连库整体查所有表，写缓存。

        新逻辑：缓存整体有效就用、无效就整体重查（不按表补缺）。
        """
        cache_path = tmp_path / "schema_cache.json"
        import json
        # 空缓存（cached_at 空 → 视为过期 → 整体重查）
        cache_path.write_text(json.dumps({"cached_at": "", "tables": {}}), encoding="utf-8")

        executor_called = {"n": 0}
        def tracking(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, cache_path)

        assert executor_called["n"] == 1, "缓存无效应整体连库查一次"
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"查到后应校验通过: {db_errors}"
        # 缓存应被写入（含 ods_test_f）
        updated = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "ods.ods_test_f" in updated["tables"]

    def test_cache_partial_miss_refreshes(self, tmp_path, monkeypatch):
        """缓存有效（未过期）但缺某张表 → 不当命中，连库刷新补齐（防误报表不存在）。"""
        cache_path = tmp_path / "schema_cache.json"
        import json
        # 缓存有效但只有 table_a，没有 ods_test_f（本次要查的）
        cache_path.write_text(json.dumps({
            "cached_at": "2099-01-01T00:00:00",
            "tables": {"ods.table_a": ["x"]},
        }), encoding="utf-8")

        executor_called = {"n": 0}
        def tracking(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, cache_path)

        # 缺表 → 连库刷新（不再当空集误报"字段不存在"）
        assert executor_called["n"] == 1, "缓存缺表应连库刷新"
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"刷新后应校验通过: {db_errors}"
        updated = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "ods.ods_test_f" in updated["tables"]

    def test_cache_expired_refetches(self, tmp_path, monkeypatch):
        """缓存过期（cached_at 过去很久）→ 重新连库捞。"""
        cache_path = tmp_path / "schema_cache.json"
        import json
        cache_path.write_text(json.dumps({
            "cached_at": "2020-01-01T00:00:00",  # 很久以前，已过期
            "tables": {"ods.ods_test_f": ["id"]},
        }), encoding="utf-8")

        executor_called = {"n": 0}
        def tracking(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, cache_path)

        assert executor_called["n"] == 1, "缓存过期应重新连库"

    def test_refresh_schema_forces_fetch(self, tmp_path, monkeypatch):
        """--refresh-schema 强制连库，即使缓存有效。"""
        cache_path = tmp_path / "schema_cache.json"
        import json
        cache_path.write_text(json.dumps({
            "cached_at": "2099-01-01T00:00:00",  # 未过期
            "tables": {"ods.ods_test_f": ["id"]},
        }), encoding="utf-8")

        executor_called = {"n": 0}
        def tracking(schema, config_path=""):
            executor_called["n"] += 1
            return _make_mock_executor({("ods", "ods_test_f"): ["id"]})
        monkeypatch.setattr("dws_db.create_executor_for_schema", tracking)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, cache_path, refresh_schema=True)

        assert executor_called["n"] == 1, "refresh_schema=True 应强制连库"

    def test_no_cache_no_db_skips_silently(self, tmp_path, monkeypatch):
        """无缓存 + 连不上库 → 静默跳过。"""
        def boom(schema, config_path=""):
            raise ImportError("psycopg2 未安装")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs, None)  # 无缓存

        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], "无缓存+连不上库应静默跳过"


class TestStaticChecks:
    """新增静态校验测试：表别名重复 / source_column 中文 / 字段级表级一致性。"""

    def test_duplicate_alias_blocks(self, monkeypatch):
        """实体级同别名出现多次 → error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input(
            fields=[_biz_field(source_column="id")],
            sources=[
                {"source_schema": "ods", "source_table": "t1", "source_table_cn": "t1",
                 "source_alias": "a", "target_schema": "dws", "target_table": "dwb_test_i"},
                {"source_schema": "ods", "source_table": "t2", "source_table_cn": "t2",
                 "source_alias": "a", "target_schema": "dws", "target_table": "dwb_test_i"},  # 同别名 a
            ],
        )
        result = precheck(rs)
        dup_errors = [e for e in result.errors if "别名" in e and "重复" in e]
        assert dup_errors, f"应报别名重复: {result.errors}"

    def test_chinese_source_column_blocks(self, monkeypatch):
        """source_column 含中文 → error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="订单ID")])  # 中文列名
        result = precheck(rs)
        cn_errors = [e for e in result.errors if "中文" in e]
        assert cn_errors, f"应报 source_column 中文: {result.errors}"

    def test_english_source_column_passes(self, monkeypatch):
        """source_column 是英文 → 无中文相关 error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="order_id")])  # 英文
        result = precheck(rs)
        cn_errors = [e for e in result.errors if "中文" in e]
        assert cn_errors == [], f"英文列名不应报中文错误: {cn_errors}"

    def test_field_table_mismatch_blocks(self, monkeypatch):
        """字段级的 source_table 不在实体级定义 → error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        # 实体级只有 ods_test_f，字段级写了 ods_other_table
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_other_table",  # 不在实体级
            "source_column": "id", "source_type": "bigint",
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "id", "target_column_cn": "ID",
            "target_type": "bigint", "source_alias": "t", "remark": "主键",
        }])
        result = precheck(rs)
        mismatch_errors = [e for e in result.errors if "未定义" in e]
        assert mismatch_errors, f"应报字段级表级不一致: {result.errors}"

    def test_field_table_consistent_passes(self, monkeypatch):
        """字段级的 source_table 在实体级定义 → 无不一致 error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])  # ods_test_f 在实体级
        result = precheck(rs)
        mismatch_errors = [e for e in result.errors if "未定义" in e]
        assert mismatch_errors == [], f"一致时不应报: {mismatch_errors}"

    def test_assign_field_skips_source_check(self, monkeypatch):
        """赋值字段无来源表（source_table='-'）→ 跳过表一致性/别名校验，不报错。

        BA 写赋值字段时表达式如 'NULL AS status'，preprocess 可能解析出
        source_table='-'，赋值字段本来就没有真实来源表，不该校验。
        """
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([
            _biz_field(source_column="id"),
            {"transform_rule": "赋值", "transform_detail": "NULL AS status",
             "target_column": "status", "target_column_cn": "状态",
             "target_type": "varchar(2)", "source_alias": "",
             "source_schema": "-", "source_table": "-", "source_column": "",
             "remark": ""},
        ])
        result = precheck(rs)
        source_errors = [e for e in result.errors if "未定义" in e or "别名" in e]
        assert source_errors == [], f"赋值字段无来源表不该报: {source_errors}"

    def test_direct_copy_with_expression_no_warn(self, monkeypatch):
        """直接复制填了映射表达式 → 不该 warn（BA 从关联从表取值时标注关联是习惯写法）。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([{
            "source_table": "ods_test_f", "source_column": "amt", "source_type": "numeric(10,2)",
            "transform_rule": "直接复制", "transform_detail": "关联从表b取amt",
            "target_column": "amt", "target_column_cn": "金额", "target_type": "numeric(10,2)",
            "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        expr_warns = [w for w in result.warnings if "直接复制" in w and "表达式" in w]
        assert expr_warns == [], f"直接复制填表达式不该 warn: {expr_warns}"

    def test_direct_copy_empty_alias_blocks(self, monkeypatch):
        """直接复制/数据加工字段 source_alias 为空 → error（多表 JOIN 歧义，单表也无法定位来源）。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([{
            "source_table": "ods_test_f", "source_column": "amt", "source_type": "numeric(10,2)",
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "amt", "target_column_cn": "金额", "target_type": "numeric(10,2)",
            "source_alias": "",  # ★ 空
            "remark": "",
        }])
        result = precheck(rs)
        alias_errors = [e for e in result.errors if "source_alias" in e and "为空" in e]
        assert alias_errors, f"直接复制字段 source_alias 空应报 error: {result.errors}"

    def test_assign_empty_alias_ok(self, monkeypatch):
        """赋值字段 source_alias 为空 → 不报（赋值无来源表）。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([
            _biz_field(source_column="id"),
            {"transform_rule": "赋值", "transform_detail": "'N'",
             "target_column": "status", "target_column_cn": "状态",
             "target_type": "varchar(2)", "source_alias": "",  # 赋值字段空 alias 正常
             "remark": ""},
        ])
        result = precheck(rs)
        alias_errors = [e for e in result.errors if "source_alias" in e and "为空" in e]
        assert alias_errors == [], f"赋值字段空 alias 不该报: {alias_errors}"

    def test_multi_table_union_all_single_query(self, tmp_path, monkeypatch):
        """多张表缺失 → 一条 UNION ALL SQL 查回（不是多次往返）。

        构造两张表都缺失缓存，验证只连库一次（UNION ALL 一条 SQL），
        且两张表的列都正确归属。
        """
        cache_path = tmp_path / "schema_cache.json"
        # 空缓存（两张表都要连库捞）
        cache_path.write_text('{"cached_at": "", "tables": {}}', encoding="utf-8")

        captured_sql = []
        executor = _make_mock_executor({
            ("ods", "table_a"): {"id": "bigint", "name": "character varying(64)"},
            ("dim", "table_b"): {"user_id": "bigint", "level": "integer"},
        })
        # 用 wrapper 拦截 execute 调用的 SQL
        real_side = executor.execute.side_effect
        def capture(sql):
            captured_sql.append(sql)
            return real_side(sql)
        executor.execute.side_effect = capture
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        # 两个字段来自两张不同的表
        rs = _make_rs_input(
            fields=[
                {"source_schema": "ods", "source_table": "table_a",
                 "source_column": "id", "source_type": "bigint",
                 "transform_rule": "直接复制", "transform_detail": "-",
                 "target_column": "id", "target_column_cn": "ID",
                 "target_type": "bigint", "source_alias": "a", "remark": "主键"},
                {"source_schema": "dim", "source_table": "table_b",
                 "source_column": "user_id", "source_type": "bigint",
                 "transform_rule": "直接复制", "transform_detail": "-",
                 "target_column": "user_id", "target_column_cn": "用户ID",
                 "target_type": "bigint", "source_alias": "b", "remark": ""},
            ],
            sources=[
                {"source_schema": "ods", "source_table": "table_a",
                 "source_table_cn": "表A", "source_alias": "a",
                 "target_schema": "dws", "target_table": "dwb_test_i"},
                {"source_schema": "dim", "source_table": "table_b",
                 "source_table_cn": "表B", "source_alias": "b",
                 "target_schema": "dws", "target_table": "dwb_test_i"},
            ],
        )
        result = precheck(rs, cache_path)

        # 主查询（非 SELECT 1 的 test_connection）应只有一条，含 UNION ALL
        main_sqls = [s for s in captured_sql if "pg_attribute" in s]
        assert len(main_sqls) == 1, \
            f"多表应一条 UNION ALL SQL，实际 {len(main_sqls)} 条: {main_sqls}"
        assert "UNION ALL" in main_sqls[0], f"应含 UNION ALL"
        assert "table_a" in main_sqls[0] and "table_b" in main_sqls[0]
        # 校验通过
        db_errors = [e for e in result.errors if ("字段不存在" in e or "类型不符" in e)]
        assert db_errors == [], f"两张表字段都存在应通过: {db_errors}"


class TestIncrementalChecks:
    """增量校验：标了增量必须有驱动表+增量字段，驱动表须在 source_tables 里。"""

    def _rs_incremental(self, incremental_tables, incremental_key="时间戳字段"):
        """构造增量场景的 rs_input。"""
        rs = _make_rs_input([_biz_field(source_column="id")])
        rs["schedule"]["incremental_key"] = incremental_key
        rs["schedule"]["incremental_tables"] = incremental_tables
        return rs

    def test_incremental_with_valid_driver_passes(self, monkeypatch):
        """增量场景 + 驱动表在 source_tables 里 + 有增量字段 → 通过。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = self._rs_incremental([
            {"source_table": "ods_test_f", "incremental_key": "update_time"}
        ])
        result = precheck(rs)
        incr_errors = [e for e in result.errors if "增量" in e or "驱动表" in e]
        assert incr_errors == [], f"合法增量场景应通过: {incr_errors}"

    def test_incremental_without_driver_tables_blocks(self, monkeypatch):
        """★ 标了增量但驱动表为空 → error（核心校验）。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = self._rs_incremental([])
        result = precheck(rs)
        driver_errors = [e for e in result.errors if "驱动表" in e and "为空" in e]
        assert driver_errors, f"标了增量但无驱动表应报错: {result.errors}"

    def test_full_load_with_variants_no_driver_passes(self, monkeypatch):
        """全量资产，增量识别方式含'不涉及'/'全量'变体，无驱动表 → 不该阻断。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        for variant in ["不涉及（全量调度）", "不涉及", "全量", "无"]:
            rs = self._rs_incremental([], incremental_key=variant)
            result = precheck(rs)
            incr_errors = [e for e in result.errors if "增量" in e or "驱动表" in e]
            assert incr_errors == [], f"全量变体'{variant}'不该报增量错: {incr_errors}"

    def test_incremental_driver_missing_key_blocks(self, monkeypatch):
        """驱动表没填增量字段 → error。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = self._rs_incremental([
            {"source_table": "ods_test_f", "incremental_key": ""}  # 没填增量字段
        ])
        result = precheck(rs)
        key_errors = [e for e in result.errors if "增量字段" in e]
        assert key_errors, f"驱动表没填增量字段应报错: {result.errors}"

    def test_incremental_driver_not_in_sources_blocks(self, monkeypatch):
        """★ 驱动表不在 source_tables 里 → error（核心校验）。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = self._rs_incremental([
            {"source_table": "ods_nonexistent_f", "incremental_key": "update_time"}
        ])
        result = precheck(rs)
        src_errors = [e for e in result.errors if "source_tables" in e]
        assert src_errors, f"驱动表不在 sources 里应报错: {result.errors}"

    def test_full_load_no_incremental_ok(self, monkeypatch):
        """全量场景（增量识别=不涉及）+ 无驱动表 → 通过。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = _make_rs_input([_biz_field(source_column="id")])
        rs["schedule"]["incremental_key"] = "不涉及"
        # 不设 incremental_tables（全量场景不该有）
        result = precheck(rs)
        incr_errors = [e for e in result.errors if "增量" in e or "驱动表" in e]
        assert incr_errors == [], f"全量场景不应报增量错: {incr_errors}"

    def test_full_load_but_has_driver_warns(self, monkeypatch):
        """全量场景但填了驱动表 → warn（可能漏标了增量）。"""
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        rs = _make_rs_input([_biz_field(source_column="id")])
        rs["schedule"]["incremental_key"] = "不涉及"
        rs["schedule"]["incremental_tables"] = [
            {"source_table": "ods_test_f", "incremental_key": "update_time"}
        ]
        result = precheck(rs)
        warns = [w for w in result.warnings if "增量" in w or "驱动表" in w]
        assert warns, f"全量+有驱动表应 warn: {result.warnings}"


class TestTypeCheck:
    """字段类型严格匹配检查。"""

    def test_type_match_passes(self, monkeypatch):
        """mapping 类型和库里一致 → 通过。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "character varying(64)"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        # _biz_field 默认 source_type=VARCHAR(64)，归一化后=charactervarying(64)
        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"类型一致应通过: {type_errors}"

    def test_type_mismatch_blocks(self, monkeypatch):
        """mapping 写 varchar(64)，库里是 bigint → error（阻断）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "bigint"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        # _biz_field 的 source_type=VARCHAR(64)
        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors, f"类型不符应报 error: {result.errors}"
        assert "varchar" in type_errors[0].lower() or "bigint" in type_errors[0].lower()

    def test_varchar_alias_normalized(self, monkeypatch):
        """varchar 和 character varying 归一化后应匹配。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "character varying(64)"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([_biz_field(source_column="id")])  # VARCHAR(64)
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"varchar/character varying 应归一化匹配: {type_errors}"

    def test_int_alias_normalized(self, monkeypatch):
        """整数同义归一：int8(64)/int8/bigint/int(64) 都归一 bigint（PG 内部名 int8==SQL bigint；(64)位宽=8字节）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "bigint"}  # 库返回 bigint
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        for source_type in ["int8(64)", "int8", "bigint", "int(64)"]:
            rs = _make_rs_input([{
                "source_schema": "ods", "source_table": "ods_test_f",
                "source_column": "id", "source_type": source_type,
                "transform_rule": "直接复制", "transform_detail": "-",
                "target_column": "id", "target_column_cn": "ID",
                "target_type": "bigint", "source_alias": "t", "remark": "",
            }])
            result = precheck(rs)
            type_errors = [e for e in result.errors if "类型不符" in e]
            assert type_errors == [], \
                f"source_type={source_type!r} vs 库 bigint 应归一匹配: {type_errors}"

    def test_int_bit_width_decides_precision(self, monkeypatch):
        """int(32) 位宽决定精度→integer（不是 bigint）。库是 integer 时 int(32) 通过，int(64) 报不符。"""
        # 库是 integer，mapping 标 int(32) → 都归一 integer，通过
        executor = _make_mock_executor({("ods", "ods_test_f"): {"id": "integer"}})
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "id", "source_type": "int(32)",
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "id", "target_column_cn": "ID",
            "target_type": "integer", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"int(32)==integer 应通过: {type_errors}"

    def test_varchar2_not_normalized_reports(self, monkeypatch):
        """varchar2 不归一 varchar（字节语义不同）：mapping varchar2 vs 库 character varying → 报[类型不符]。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"name": "character varying(100)"}  # 库 varchar 系
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "name", "source_type": "varchar2(100)",  # varchar2 字节语义，不归一
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "name", "target_column_cn": "name",
            "target_type": "varchar2(100)", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors, f"varchar2 vs varchar 字节语义不同应报不符: {result.errors}"

    def test_nvarchar2_not_normalized_reports(self, monkeypatch):
        """nvarchar2 不归一 varchar（字节语义不同）：mapping nvarchar2 vs 库 varchar → 报[类型不符]。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"name": "character varying(100)"}  # 库是 varchar 系
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "name", "source_type": "nvarchar2(100)",  # nvarchar2 不归一
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "name", "target_column_cn": "name",
            "target_type": "nvarchar2(100)", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors, f"nvarchar2 vs varchar 字节不同应报不符: {result.errors}"

    def test_int_precision_distinct_reports(self, monkeypatch):
        """精度不同的整数类型应报（bigint vs integer 不是同一类型）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "integer"}  # 库是 4 字节 integer
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "id", "source_type": "bigint",  # mapping 标 8 字节 bigint
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "id", "target_column_cn": "ID",
            "target_type": "bigint", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors, f"bigint vs integer 精度不同应报: {result.errors}"

    def test_no_source_type_skips_type_check(self, monkeypatch):
        """mapping 没写 source_type（空）→ 不查类型（只查存在性）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"id": "bigint"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        # source_type 为空
        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "id", "source_type": "",  # 空，不查类型
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "id", "target_column_cn": "ID",
            "target_type": "VARCHAR(64)", "source_alias": "t", "remark": "主键",
        }])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"source_type 空不应查类型: {type_errors}"

    def test_one_source_to_multi_target_single_error(self, monkeypatch):
        """一个来源字段映射多个目标 → 类型错只报一次（以来源字段为主语，显示目标数）。

        amount 映射到 total_amount 和 refund_amount 两个字段。
        amount 类型错 → 只报一条（amount 的错），不重复报两个目标的。
        """
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"amount": "bigint"}  # 库里 bigint
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        # 同一来源 amount 映射到两个目标
        rs = _make_rs_input([
            {"source_schema": "ods", "source_table": "ods_test_f",
             "source_column": "amount", "source_type": "DECIMAL(18,2)",
             "transform_rule": "数据加工", "transform_detail": "SUM(amount)",
             "target_column": "total_amount", "target_column_cn": "总额",
             "target_type": "DECIMAL(18,2)", "source_alias": "t", "remark": ""},
            {"source_schema": "ods", "source_table": "ods_test_f",
             "source_column": "amount", "source_type": "DECIMAL(18,2)",
             "transform_rule": "数据加工", "transform_detail": "SUM(amount) for refund",
             "target_column": "refund_amount", "target_column_cn": "退款额",
             "target_type": "DECIMAL(18,2)", "source_alias": "t", "remark": ""},
        ])
        result = precheck(rs)

        type_errors = [e for e in result.errors if "类型不符" in e]
        # 只报一条（amount 类型错），不是两条
        assert len(type_errors) == 1, f"应只报一条来源字段类型错，实际{len(type_errors)}: {type_errors}"
        # 报错以来源字段为主语
        assert "amount" in type_errors[0]
        # 显示"2个目标字段"（不是某个具体目标）
        assert "2个目标字段" in type_errors[0]

    def test_one_source_to_single_target_shows_target_name(self, monkeypatch):
        """一个来源映射单个目标 → 报错显示具体目标名（不是数量）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"amount": "bigint"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "amount", "source_type": "DECIMAL(18,2)",
            "transform_rule": "数据加工", "transform_detail": "SUM(amount)",
            "target_column": "total_amount", "target_column_cn": "总额",
            "target_type": "DECIMAL(18,2)", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)

        type_errors = [e for e in result.errors if "类型不符" in e]
        assert len(type_errors) == 1
        # 单目标时显示具体目标名
        assert "total_amount" in type_errors[0]

    def _ts_field(self, source_type, db_type, source_column="create_time"):
        """构造一个 timestamp 类型字段映射行。"""
        return {
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": source_column, "source_type": source_type,
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": source_column, "target_column_cn": "创建时间",
            "target_type": source_type, "source_alias": "t",
        }

    def test_timestamp_precision_ignored(self, monkeypatch):
        """timestamp vs timestamp(0) 精度差异忽略（都无时区）→ 通过。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"create_time": "timestamp(0) without time zone"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([self._ts_field("timestamp", "timestamp(0) without time zone")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"timestamp 精度差异应忽略: {type_errors}"

    def test_timestamp_without_tz_variants_match(self, monkeypatch):
        """timestamp / timestamp(0) / timestamp without time zone 互通（同族无时区）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"create_time": "timestamp(6) without time zone"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([self._ts_field("timestamp(0)", "timestamp(6) without time zone")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"无时区 timestamp 同族应互通: {type_errors}"

    def test_timestamptz_variants_match(self, monkeypatch):
        """timestamptz / timestamp(n) with time zone 互通（同族有时区）。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"create_time": "timestamp(0) with time zone"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        rs = _make_rs_input([self._ts_field("timestamptz", "timestamp(0) with time zone")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors == [], f"有时区 timestamp 同族应互通: {type_errors}"

    def test_timestamp_with_vs_without_tz_mismatch(self, monkeypatch):
        """timestamp（无时区）vs timestamptz（有时区）底层不同 → 仍判不符。"""
        executor = _make_mock_executor({
            ("ods", "ods_test_f"): {"create_time": "timestamp with time zone"}
        })
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)
        # mapping 写无时区，库里有时区 → 底层不同，应报不符
        rs = _make_rs_input([self._ts_field("timestamp", "timestamp with time zone")])
        result = precheck(rs)
        type_errors = [e for e in result.errors if "类型不符" in e]
        assert type_errors, f"with/without 时区底层不同应报不符: {result.errors}"


class TestNormalizeType:
    """_normalize_type 单元测试：类型同义异名归一（纯函数，不连库）。

    与 TestTypeCheck（集成，跑完整 precheck）互补：这里精确锁住归一逻辑。
    """

    def _n(self, t):
        from precheck import _normalize_type
        return _normalize_type(t)

    def test_int_aliases_same_precision(self):
        """同精度整数别名归一：8字节族/4字节族/2字节族内部互通。"""
        # 8 字节（PG 内部名 int8 == SQL 标准名 bigint）
        for t in ["bigint", "int8", "bigserial"]:
            assert self._n(t) == "bigint", f"{t!r} 应归一 bigint，实际 {self._n(t)!r}"
        # 4 字节
        for t in ["integer", "int", "int4", "serial"]:
            assert self._n(t) == "integer", f"{t!r} 应归一 integer，实际 {self._n(t)!r}"
        # 2 字节
        for t in ["smallint", "int2", "smallserial"]:
            assert self._n(t) == "smallint", f"{t!r} 应归一 smallint，实际 {self._n(t)!r}"

    def test_int_bit_width_decides_precision(self):
        """(n) 位宽优先决定整数精度：int8(64)/int(64)→bigint，int(32)/int4(32)→integer，int2(16)→smallint。"""
        # 64bit → bigint
        assert self._n("int8(64)") == "bigint"
        assert self._n("int(64)") == "bigint"
        # 32bit → integer
        assert self._n("int(32)") == "integer"
        assert self._n("int4(32)") == "integer"
        # 16bit → smallint
        assert self._n("int2(16)") == "smallint"
        # 非标准位宽（如 20）→ fallback 到 base name
        assert self._n("int(20)") == "integer"  # base int → integer

    def test_int_different_precision_not_equal(self):
        """不同精度的整数类型不归一（bigint != integer != smallint）。"""
        assert self._n("bigint") != self._n("integer")
        assert self._n("integer") != self._n("smallint")
        # int(64) 是 bigint，int(32) 是 integer，位宽不同精度不同
        assert self._n("int(64)") != self._n("int(32)")

    def test_varchar_aliases_with_length(self):
        """字符类别名归一 + 保留长度后缀。varchar2/nvarchar2 都不归一（字节/字符语义不同）。"""
        assert self._n("varchar(100)") == self._n("character varying(100)") == "charactervarying(100)"
        assert self._n("char(10)") == self._n("character(10)") == "character(10)"
        # varchar2/nvarchar2 都不归一到 varchar（字节/字符语义不同，归一会漏判长度超长）
        assert self._n("varchar2(100)") == "varchar2(100)"
        assert self._n("varchar2(100)") != self._n("varchar(100)")
        assert self._n("nvarchar2(100)") == "nvarchar2(100)"
        assert self._n("nvarchar2(100)") != self._n("varchar(100)")

    def test_numeric_aliases_with_precision(self):
        """数值类别名归一 + 保留精度后缀。"""
        assert self._n("decimal(18,2)") == self._n("numeric(18,2)") == "numeric(18,2)"

    def test_numeric_different_precision_not_equal(self):
        """numeric 精度不同不归一（长度后缀要保留参与对比）。"""
        assert self._n("numeric(18,2)") != self._n("numeric(15,2)")
        assert self._n("varchar(100)") != self._n("varchar(50)")

    def test_timestamp_tz_split(self):
        """timestamp 的 with/without time zone 底层不同，分开归一。"""
        assert self._n("timestamp") == self._n("timestamp(0)") == "ts_notz"
        assert self._n("timestamptz") == self._n("timestamp with time zone") == "ts_tz"
        assert self._n("timestamp") != self._n("timestamptz")

    def test_other_aliases(self):
        """其他常见别名归一。"""
        assert self._n("bool") == self._n("boolean") == "boolean"
        assert self._n("string") == self._n("text") == "text"


# ============================================================
# 类型决策回写 rs_input（precheck._apply_type_decision）
# ============================================================

class TestApplyTypeDecision:
    """决策通过后回写 rs_input：转换/加安全处理字段改"数据加工"（嵌入主链路）。"""

    @staticmethod
    def _write_decision(tmp_path, batch_strategy="", batch_cols=(), ind_actions=None):
        import yaml
        dec = {
            "批量处置策略": batch_strategy,
            "常规风险字段": [
                {"目标字段": c, "源类型": "varchar(200)", "目标类型": "varchar(50)", "风险": "长度超长"}
                for c in batch_cols
            ],
            "跨大类风险字段": [
                {"目标字段": c, "源类型": "varchar(20)", "目标类型": "date", "风险": "跨大类", "处置": a, "原因": ""}
                for c, a in (ind_actions or {}).items()
            ],
        }
        p = tmp_path / "type_risk_decision.yaml"
        p.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        return p

    @staticmethod
    def _fm(rs, col):
        return next(f for f in rs["field_mappings"] if f["target_column"] == col)

    def test_batch_safe_processing_rewrites(self, tmp_path):
        """批量'加安全处理' → 字段改数据加工 + 标注安全处理。"""
        from precheck import _apply_type_decision
        from conftest import make_type_risk_rs_input
        rs = make_type_risk_rs_input([{"target_column": "remark", "source_type": "varchar(200)", "target_type": "varchar(50)"}])
        dp = self._write_decision(tmp_path, batch_strategy="加安全处理", batch_cols=("remark",))
        assert _apply_type_decision(rs, dp) == 1
        fm = self._fm(rs, "remark")
        assert fm["transform_rule"] == "数据加工"
        assert "类型安全处理" in fm["transform_detail"]

    def test_individual_convert_rewrites(self, tmp_path):
        """跨大类'转换' → 字段改数据加工 + 标注类型转换。"""
        from precheck import _apply_type_decision
        from conftest import make_type_risk_rs_input
        rs = make_type_risk_rs_input([{"target_column": "biz_date", "source_type": "varchar(20)", "target_type": "date"}])
        dp = self._write_decision(tmp_path, ind_actions={"biz_date": "转换"})
        assert _apply_type_decision(rs, dp) == 1
        fm = self._fm(rs, "biz_date")
        assert fm["transform_rule"] == "数据加工"
        assert "类型转换" in fm["transform_detail"]
        assert "改 ETL 不改 DDL" in fm["transform_detail"]

    def test_no_action_not_rewritten(self, tmp_path):
        """决策'不加'/未启用批量 → 字段保持直接复制。"""
        from precheck import _apply_type_decision
        from conftest import make_type_risk_rs_input
        rs = make_type_risk_rs_input()
        dp = self._write_decision(tmp_path, batch_strategy="不加")
        assert _apply_type_decision(rs, dp) == 0
        # 全是审计+直取字段，无风险字段命中

    def test_idempotent_already_processed(self, tmp_path):
        """幂等：已是数据加工的字段不再改（回写后重跑不重复）。"""
        from precheck import _apply_type_decision
        from conftest import make_type_risk_rs_input
        rs = make_type_risk_rs_input([{"target_column": "remark", "source_type": "varchar(200)", "target_type": "varchar(50)"}])
        dp = self._write_decision(tmp_path, batch_strategy="加安全处理", batch_cols=("remark",))
        assert _apply_type_decision(rs, dp) == 1
        assert _apply_type_decision(rs, dp) == 0  # 第二次：已是数据加工，跳过

    def test_missing_decision_file_returns_zero(self, tmp_path):
        """决策文件不存在 → 0（不抛异常）。"""
        from precheck import _apply_type_decision
        from conftest import make_type_risk_rs_input
        rs = make_type_risk_rs_input()
        assert _apply_type_decision(rs, tmp_path / "nope.yaml") == 0


# ============================================================
# 任务二：校验分级与容错（源表别名升 error + error 消息修复指引）
# ============================================================

class TestAliasGradingAndGuidance:
    """源表级 source_alias 空升 error；error 消息含修复指引（指向 mapping.xlsx）。"""

    def test_source_table_empty_alias_is_error(self, monkeypatch):
        """源表级 source_alias 空 → error（不再是 warn）。源头拦更清晰。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input(
            fields=[_biz_field(source_column="id")],
            sources=[{"source_schema": "ods", "source_table": "ods_test_f",
                      "source_table_cn": "测试源表", "source_alias": "",  # ★ 空
                      "target_schema": "dws", "target_table": "dwb_test_i"}],
        )
        result = precheck(rs)
        # 源表级别名空应作为 error（消息含"源表"+"别名"）
        src_alias_errors = [
            e for e in result.errors
            if "源表" in e and "别名" in e and "source_alias" in e
        ]
        assert src_alias_errors, f"源表级 source_alias 空应报 error: {result.errors}"
        # 不应作为 warning 出现
        src_alias_warns = [
            w for w in result.warnings
            if "源表" in w and "source_alias" in w
        ]
        assert src_alias_warns == [], f"源表级别名空已升 error，不应再 warn: {src_alias_warns}"

    def test_source_alias_error_has_mapping_xlsx_guidance(self, monkeypatch):
        """源表级别名空的 error 含修复指引关键词 mapping.xlsx。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input(
            fields=[_biz_field(source_column="id")],
            sources=[{"source_schema": "ods", "source_table": "ods_test_f",
                      "source_table_cn": "测试源表", "source_alias": "",
                      "target_schema": "dws", "target_table": "dwb_test_i"}],
        )
        result = precheck(rs)
        guidance = [e for e in result.errors if "mapping.xlsx" in e]
        assert guidance, f"error 应含 mapping.xlsx 修复指引: {result.errors}"

    def test_field_missing_source_column_has_guidance(self, monkeypatch):
        """直接复制缺 source_column 的 error 含 mapping.xlsx 指引。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "", "source_type": "bigint",
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": "amt", "target_column_cn": "金额",
            "target_type": "bigint", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        missing = [e for e in result.errors if "来源字段" in e and "mapping.xlsx" in e]
        assert missing, f"缺 source_column 的 error 应含 mapping.xlsx 指引: {result.errors}"

    def test_invalid_mapping_rule_has_guidance(self, monkeypatch):
        """映射规则不合法的 error 含'改为 ... 之一'指引。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "amt", "source_type": "bigint",
            "transform_rule": "查表",  # ★ 不合法
            "transform_detail": "-",
            "target_column": "amt", "target_column_cn": "金额",
            "target_type": "bigint", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        invalid = [e for e in result.errors if "不合法" in e and "改为" in e]
        assert invalid, f"非法映射规则 error 应含'改为'指引: {result.errors}"

    def test_derived_empty_source_column_stays_warn(self, monkeypatch):
        """数据加工 source_column 空 → 仍 warn（纯派生如 COUNT(*) 合法），不升 error。"""
        def boom(schema, config_path=""):
            raise ImportError("skip db")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([{
            "source_schema": "ods", "source_table": "ods_test_f",
            "source_column": "", "source_type": "bigint",
            "transform_rule": "数据加工", "transform_detail": "COUNT(*)",
            "target_column": "cnt", "target_column_cn": "计数",
            "target_type": "bigint", "source_alias": "t", "remark": "",
        }])
        result = precheck(rs)
        derived_warns = [w for w in result.warnings if "纯派生" in w or "来源字段" in w]
        assert derived_warns, f"数据加工无来源字段应 warn: {result.warnings}"
        # 不应是 error
        derived_errors = [e for e in result.errors if "数据加工" in e and "没有来源字段" in e]
        assert derived_errors == [], f"纯派生不应报 error: {derived_errors}"


class TestJoinConditionGate:
    """入口闸：join_condition 引用字段存在性 + 逻辑字段出处（泛化 rn 案例族）。"""

    def _rs(self, join_a="a.oid = b.oid and a.rn = 1", join_m="m.cid = c.cid and m.rn = 1",
            detail_on_a=None):
        fm = [
            {"source_table": "ods_a_f", "source_column": "oid", "source_type": "bigint",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "oid", "target_column_cn": "OID", "target_type": "bigint",
             "source_alias": "a", "remark": ""},
        ]
        if detail_on_a:
            fm.append({
                "source_table": "ods_a_f", "source_column": "", "source_type": "",
                "transform_rule": "数据加工", "transform_detail": detail_on_a,
                "target_column": "latest_flag", "target_column_cn": "最新标记",
                "target_type": "varchar(10)", "source_alias": "a", "remark": ""})
        return {
            "field_mappings": fm,
            "source_tables": [
                {"source_schema": "ods", "source_table": "ods_a_f", "source_table_cn": "A",
                 "source_alias": "a", "join_condition": join_a},
                {"source_schema": "ods", "source_table": "ods_b_f", "source_table_cn": "B",
                 "source_alias": "b", "join_condition": ""},
                {"source_schema": "ods", "source_table": "ods_m_f", "source_table_cn": "M",
                 "source_alias": "m", "join_condition": join_m},
            ],
            "meta": {},
        }

    def _cache(self, tmp_path):
        import json as _json
        cache = {"cached_at": "", "tables": {
            "ods.ods_a_f": {"oid": "bigint"},
            "ods.ods_b_f": {"oid": "bigint"},
            "ods.ods_m_f": {"cid": "bigint"},
            "ods.ods_c_f": {"cid": "bigint"},
        }}
        p = tmp_path / "schema_cache.json"
        p.write_text(_json.dumps(cache), encoding="utf-8")
        return p

    def _run(self, rs, cache_path):
        from precheck import _check_join_conditions, PrecheckResult
        result = PrecheckResult()
        _check_join_conditions(rs, result, cache_path, None)
        return result

    def test_no_provenance_hard_error(self, tmp_path):
        """两处 rn 均无出处 → error（copy 残留/笔误）。"""
        rs = self._rs()
        result = self._run(rs, self._cache(tmp_path))
        errs = [e for e in result.errors if "rn" in e]
        assert len(errs) >= 2, result.errors

    def test_provenance_scoped_per_table(self, tmp_path):
        """A 表有出处（字段行记载），M 表没有 → 只有 M 报（作用域隔离不冒领）。"""
        rs = self._rs(detail_on_a="取最新：ROW_NUMBER() OVER(PARTITION BY oid ORDER BY upd DESC) rn，限定 rn=1")
        result = self._run(rs, self._cache(tmp_path))
        a_errs = [e for e in result.errors if "ods_a_f" in e and "rn" in e]
        m_errs = [e for e in result.errors if "ods_m_f" in e and "rn" in e]
        assert not a_errs, f"A 有出处不该报: {a_errs}"
        assert m_errs, "M 无出处应报"
        assert any("designer 落地" in p for p in result.passed), result.passed  # 放行+落地提示
        assert any(i["field"] == "rn" and i["level"] == "note"
                   for i in rs["_condition_issues"])

    def test_typo_family_caught(self, tmp_path):
        """笔误家族（cust_id vs 表里无此列）同一机制收编 → error。"""
        rs = self._rs(join_a="a.oid = b.cust_id", join_m="")
        result = self._run(rs, self._cache(tmp_path))
        assert any("cust_id" in e for e in result.errors), result.errors

    def test_weak_mode_warns_without_structure(self, tmp_path):
        """未连库无缓存：无出处且不在 mapping 字段集 → warn（join-only 键合法不 error）。"""
        rs = self._rs()
        result = self._run(rs, tmp_path / "not_exist.json")
        warns = [w for w in result.warnings if "rn" in w]
        assert warns, result.warnings
        assert not any("rn" in e for e in result.errors)

    def test_pure_reference_not_self_provenance(self, tmp_path):
        """纯引用不自证：条件 'a.rn = 1' 里的 rn 不算出处（无其他记载仍报）。"""
        rs = self._rs()
        result = self._run(rs, self._cache(tmp_path))
        assert any("rn" in e for e in result.errors)


class TestJoinConditionKeywordWarn:
    """join_condition 含 SQL 关键字 → warn（输入代码是描述不是规格，designer 归位）。"""

    def test_where_in_condition_warns(self):
        from precheck import _check_join_conditions, PrecheckResult
        rs = {"field_mappings": [], "source_tables": [
            {"source_schema": "ods", "source_table": "ods_a_f", "source_alias": "a",
             "join_condition": "a.oid = b.oid where b.status = 'N'"}], "meta": {}}
        # 关键字检查在 precheck() 静态段；这里直接构造 precheck 调用太重，用内部逻辑等价验证
        import re as _re
        cond = rs["source_tables"][0]["join_condition"]
        hits = [kw for kw in ("where", "left join") if _re.search(rf'\b{kw}\b', cond, _re.I)]
        assert "where" in hits

    def test_keyword_check_via_precheck(self, tmp_path):
        from precheck import precheck
        rs = {"field_mappings": [
                {"source_table": "ods_a_f", "source_column": "id", "source_type": "bigint",
                 "transform_rule": "直接复制", "transform_detail": "-",
                 "target_column": "id", "target_column_cn": "ID", "target_type": "bigint",
                 "source_alias": "a", "remark": ""}],
              "source_tables": [
                {"source_schema": "ods", "source_table": "ods_a_f", "source_alias": "a",
                 "join_condition": "left join on a.id = b.id"}],
              "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_t_f"}}}}
        result = precheck(rs, tmp_path / "no_cache.json", False,
                          tmp_path / "dec.yaml", None)
        assert any("SQL 关键字" in w for w in result.warnings), result.warnings


class TestDbScopeExpansion:
    """DB 校验范围扩围：纯关联表进 fetch/缓存（修'未连库'误报根因）+ 大小写归一 + 表级存在性。"""

    def test_join_only_table_fetched_and_cached(self, tmp_path, monkeypatch):
        """纯关联表（无字段映射，只在 join_condition）→ 也被 fetch 并写缓存（键小写）。"""
        rs = _make_rs_input([_biz_field(source_column="id")])
        import json
        rs["source_tables"].append({
            "source_schema": "ODS", "source_table": "ODS_JOIN_ONLY_F",  # ★ mapping 大写
            "source_table_cn": "纯关联", "source_alias": "j",
            "join_condition": "t.id = j.order_id"})
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": _make_mock_executor({
                                ("ods", "ods_test_f"): ["id"],
                                ("ods", "ods_join_only_f"): ["order_id"]}))
        cache_path = tmp_path / "schema_cache.json"
        result = precheck(rs, cache_path)
        assert not any("表不存在" in e for e in result.errors), result.errors
        updated = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "ods.ods_join_only_f" in updated["tables"]  # 大写 mapping → 缓存键小写归一

    def test_join_only_table_missing_errors(self, tmp_path, monkeypatch):
        """纯关联表库中查无 → 表级 error（ETL 必然失败，不静默降级成字段误报）。"""
        rs = _make_rs_input([_biz_field(source_column="id")])
        rs["source_tables"].append({
            "source_schema": "ods", "source_table": "ods_ghost_f",
            "source_table_cn": "幽灵表", "source_alias": "g",
            "join_condition": "t.id = g.order_id"})
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": _make_mock_executor({
                                ("ods", "ods_test_f"): ["id"]}))  # ghost 表 fetch 为空
        result = precheck(rs, tmp_path / "c.json")
        assert any("ods_ghost_f" in e and "表不存在" in e for e in result.errors), result.errors

    def test_gate_message_three_states(self, tmp_path):
        """gate 弱分支文案三态：无缓存文件='未连库'；有缓存但表不在='表不在 schema 缓存'。"""
        import json
        from precheck import _check_join_conditions, PrecheckResult
        rs = {"field_mappings": [], "source_tables": [
            {"source_schema": "ods", "source_table": "ods_a_f", "source_alias": "a",
             "join_condition": "a.oid = a.rn"}], "meta": {}}
        # 无缓存文件
        r1 = PrecheckResult()
        _check_join_conditions(rs, r1, tmp_path / "none.json", None)
        assert any("未连库（无 schema_cache）" in w for w in r1.warnings)
        # 有缓存但该表不在（缓存范围没覆盖）
        cp = tmp_path / "schema_cache.json"
        cp.write_text(json.dumps({"tables": {"ods.other_f": {"x": "bigint"}}}), encoding="utf-8")
        r2 = PrecheckResult()
        _check_join_conditions(rs, r2, cp, None)
        assert any("表不在 schema 缓存" in w for w in r2.warnings), r2.warnings
        assert not any("未连库" in w for w in r2.warnings)


class TestCaseInsensitiveIdentifiers:
    """标识符（表/字段/别名/schema）大小写不敏感——只有值才敏感。"""

    def test_alias_and_table_case_mismatch_passes(self):
        from precheck import precheck
        rs = {
            "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_t_f", "cn": "t"},
                                "i_view": {"schema": "dws", "table": "dwb_t_i", "cn": "t"}}},
            "source_tables": [{"source_schema": "ODS", "source_table": "ODS_T", "source_alias": "T",
                               "source_table_cn": "测试"}],
            "field_mappings": [{"source_schema": "ods", "source_table": "ods_t", "source_alias": "t",
                                 "source_column": "id", "source_type": "bigint",
                                 "transform_rule": "直接复制", "transform_detail": "-",
                                 "target_column": "id", "target_column_cn": "ID",
                                 "target_type": "bigint"}],
            "schedule": {"strategy": "全量调度", "frequency": "T+1",
                         "incremental_key": "不涉及", "incremental_tables": [], "upstream": []},
            "_no_rs_mode": True,
        }
        result = precheck(rs)
        alias_errs = [e for e in result.errors if "来源别名" in e or "未定义" in e]
        assert not alias_errs, alias_errs
