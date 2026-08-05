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
    return {
        "source_schema": "ods", "source_table": "ods_test_f",
        "source_column": source_column, "source_type": "VARCHAR(64)",
        "transform_rule": rule, "transform_detail": "-",
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

    table_columns: {(schema, table): [col1, col2, ...]}
    executor.execute(sql) 返回带 .success/.rows 的 mock。
    """
    executor = MagicMock()
    executor.test_connection.return_value = True

    def fake_execute(sql):
        # 解析 SQL 里的 table_schema / table_name
        result = MagicMock()
        result.success = True
        result.error = ""
        rows = []
        for (sch, tbl), cols in table_columns.items():
            if f"table_schema = '{sch}'" in sql and f"table_name = '{tbl}'" in sql:
                rows = [{"column_name": c} for c in cols]
                break
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
        """表在库里不存在 → error（阻断）。"""
        executor = _make_mock_executor({})  # 空字典 = 表不存在
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": executor)

        rs = _make_rs_input([_biz_field(source_column="id")])
        result = precheck(rs)

        db_errors = [e for e in result.errors if "DB 校验" in e]
        assert any("ods_test_f" in e and "不存在" in e for e in db_errors), \
            f"表不存在应报 error: {db_errors}"
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
        # 应有 DB 校验通过的 pass
        db_passes = [p for p in result.passed if "DB 校验" in p]
        assert len(db_passes) >= 2  # 至少"已连库"+"校验了 N 个字段"

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
