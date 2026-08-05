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

# conftest 已把 design-dev-shared/references 加入 sys.path
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


def _make_mock_executor(table_columns: dict):
    """构造 mock executor。

    table_columns: {(schema, table): [col1, col2, ...]} 表示库里实际存在的列。
    适配 UNION ALL 批量查询：一条 SQL 含所有表的 UNION ALL 分支，
    每个分支带 nsp/rel/col 三列标记。
    """
    executor = MagicMock()
    executor.test_connection.return_value = True

    def fake_execute(sql):
        result = MagicMock()
        result.success = True
        result.error = ""
        rows = []
        # UNION ALL 的每个分支含 SELECT 'sch' AS nsp, 'tbl' AS rel, ...
        # 按 SQL 里出现的 (schema, table) 匹配，返回该表全部列
        for (sch, tbl), existing_cols in table_columns.items():
            sch_l = sch.lower()
            tbl_l = tbl.lower()
            if f"'{sch_l}' AS nsp" in sql and f"'{tbl_l}' AS rel" in sql:
                for c in existing_cols:
                    rows.append({"nsp": sch_l, "rel": tbl_l, "col": c})
        result.rows = rows
        return result

    executor.execute.side_effect = fake_execute
    return executor


# ============================================================
# 测试用例
# ============================================================

class TestCheckDbSchema:
    """DB 校验逻辑测试。"""

    def test_no_db_skips_silently(self, monkeypatch):
        """连不上库（create_executor_for_schema 抛异常）→ 静默跳过，不阻断。"""
        def boom(schema, config_path=""):
            raise ImportError("psycopg2 未安装")
        monkeypatch.setattr("dws_db.create_executor_for_schema", boom)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        # 不应有 DB 校验相关的 error
        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert db_errors == [], f"连不上库不应报 DB error: {db_errors}"

    def test_connection_fails_skips_silently(self, monkeypatch):
        """test_connection 返回 False → 静默跳过。"""
        executor = MagicMock()
        executor.test_connection.return_value = False
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert db_errors == [], f"连接失败不应报 DB error: {db_errors}"

    def test_table_not_exists_blocks(self, monkeypatch):
        """表在库里不存在 → 它的字段全部查不到，报字段不存在（阻断）。

        新逻辑不单独查表存在性：表不存在 = 用到的字段全查不到，统一报字段不存在。
        """
        executor = _make_mock_executor({})  # 空字典 = 库里没这张表的任何列
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert db_errors == [], f"纯派生字段不应被校验: {db_errors}"

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
        db_errors = [e for e in result.errors if "DB 校验" in e]
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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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
        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert db_errors == [], f"查到后应校验通过: {db_errors}"
        # 缓存应被写入（含 ods_test_f）
        updated = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "ods.ods_test_f" in updated["tables"]

    def test_cache_valid_partial_miss_uses_cache(self, tmp_path, monkeypatch):
        """缓存有效（未过期）但缺某张表 → 仍用缓存（该表当空集，报字段不存在）。

        新逻辑不做按表补缺：缓存整体有效就用，缺的表当空集处理。
        想刷新用 --refresh-schema。
        """
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

        # 不连库（缓存有效）
        assert executor_called["n"] == 0, "缓存有效不连库"
        # ods_test_f 不在缓存 → 当空集 → 报 id 不存在
        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert any("id" in e and "不存在" in e for e in db_errors), \
            f"缓存缺该表应报字段不存在: {db_errors}"

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

        db_errors = [e for e in result.errors if "DB 校验" in e]
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
            ("ods", "table_a"): ["id", "name"],
            ("dim", "table_b"): ["user_id", "level"],
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
        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert db_errors == [], f"两张表字段都存在应通过: {db_errors}"
