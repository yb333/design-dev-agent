"""explore.py 测试：JOIN 键唯一性试算。

只测纯逻辑函数（SQL 拼接 / 结果格式化 / 跳过提示），不连库。
连库路径（run_join_key_check）用 monkeypatch mock 掉 dws_db。

核心约束（来自 idle-task 任务三）：
- 复用 dws_db.create_executor_for_schema，不重写连库逻辑
- 只读单表，不 JOIN（不会发散）
- 连不上库静默跳过，退出码 0 不阻断设计
"""

import json
import pytest

from explore import (
    build_join_key_sql,
    format_join_key_result,
    format_skip,
    run_join_key_check,
    read_target_schema,
)


# ============================================================
# build_join_key_sql：SQL 拼接（带/不带 where）
# ============================================================

class TestBuildJoinKeySql:
    def test_basic_no_where(self):
        sql = build_join_key_sql("dim", "dim_store", "store_id")
        assert sql == (
            "SELECT count(*) AS total, count(DISTINCT store_id) AS distinct_cnt "
            "FROM dim.dim_store"
        )

    def test_with_where(self):
        sql = build_join_key_sql("dim", "dim_store", "store_id", "is_current = 1")
        assert sql.endswith("WHERE is_current = 1")
        assert "count(DISTINCT store_id)" in sql

    def test_where_whitespace_stripped(self):
        """where 前后空白被 strip，但内部表达式不动。"""
        sql = build_join_key_sql("dim", "dim_store", "store_id", "  is_current = 1  ")
        assert "WHERE is_current = 1" in sql

    def test_empty_where_no_where_clause(self):
        """空 where -> 不加 WHERE 子句。"""
        sql = build_join_key_sql("dim", "dim_store", "store_id", "")
        assert "WHERE" not in sql

    def test_missing_args_raise(self):
        """schema/table/key 任一缺 -> ValueError。"""
        with pytest.raises(ValueError):
            build_join_key_sql("", "dim_store", "store_id")
        with pytest.raises(ValueError):
            build_join_key_sql("dim", "", "store_id")
        with pytest.raises(ValueError):
            build_join_key_sql("dim", "dim_store", "")

    def test_sql_injection_rejected(self):
        """非法标识符（含 SQL 注入字符）被拒绝。"""
        with pytest.raises(ValueError):
            build_join_key_sql("dim", "dim_store", "store_id; DROP TABLE x")


# ============================================================
# format_join_key_result：唯一/不唯一结论格式化
# ============================================================

class TestFormatJoinKeyResult:
    def test_unique_verdict(self):
        out = format_join_key_result("dim", "dim_store", "store_id",
                                     total=100, distinct_cnt=100)
        assert "dim.dim_store" in out
        assert "store_id" in out
        assert "总行数: 100" in out
        assert "去重数: 100" in out
        assert "重复数: 0" in out
        assert "✅" in out
        assert "唯一" in out

    def test_not_unique_verdict(self):
        out = format_join_key_result("dim", "dim_store", "store_id",
                                     total=141753, distinct_cnt=141750)
        assert "重复数: 3" in out
        assert "❌" in out
        assert "不唯一" in out
        assert "对齐策略" in out

    def test_where_note_included(self):
        """有 where 限定 -> 输出标注限定条件。"""
        out = format_join_key_result("dim", "dim_store", "store_id",
                                     total=100, distinct_cnt=100,
                                     where_clause="is_current = 1")
        assert "限定" in out
        assert "is_current = 1" in out

    def test_no_where_note_when_empty(self):
        """无 where -> 不出限定标注。"""
        out = format_join_key_result("dim", "dim_store", "store_id",
                                     total=100, distinct_cnt=100, where_clause="")
        assert "限定" not in out


# ============================================================
# format_skip：跳过提示
# ============================================================

class TestFormatSkip:
    def test_skip_message_format(self):
        msg = format_skip("数据库连接失败")
        assert "⚠️" in msg
        assert "跳过试算" in msg
        assert "数据库连接失败" in msg


# ============================================================
# run_join_key_check：连库路径（mock dws_db）
# ============================================================

class TestRunJoinKeyCheck:
    """mock 掉 dws_db 模块，验证 run_join_key_check 的连库/失败/异常分流。"""

    def test_success_unique(self, monkeypatch):
        class FakeResult:
            success = True
            rows = [{"total": 100, "distinct_cnt": 100}]
            error = ""

        class FakeExecutor:
            def test_connection(self):
                return True

            def execute(self, sql):
                return FakeResult()

            def close(self):
                pass

        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                return FakeExecutor()

        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_join_key_check("dws", "dim", "dim_store", "store_id", "is_current = 1")
        assert "✅" in out
        assert "总行数: 100" in out

    def test_success_not_unique(self, monkeypatch):
        class FakeResult:
            success = True
            rows = [{"total": 200, "distinct_cnt": 150}]
            error = ""

        class FakeExecutor:
            def test_connection(self): return True
            def execute(self, sql): return FakeResult()
            def close(self): pass

        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                return FakeExecutor()

        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_join_key_check("dws", "dim", "dim_store", "store_id")
        assert "❌" in out
        assert "重复数: 50" in out

    def test_no_db_config_skips(self, monkeypatch):
        """连不上库（create_executor 抛异常）-> 跳过提示，不抛。"""
        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                raise FileNotFoundError("db-sources.json 不存在")

        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_join_key_check("dws", "dim", "dim_store", "store_id")
        assert "⚠️" in out
        assert "跳过试算" in out

    def test_connection_fails_skips(self, monkeypatch):
        """test_connection 返回 False -> 跳过。"""
        class FakeExecutor:
            def test_connection(self): return False
            def close(self): pass

        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                return FakeExecutor()

        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_join_key_check("dws", "dim", "dim_store", "store_id")
        assert "跳过试算" in out

    def test_sql_failure_skips(self, monkeypatch):
        """execute 返回 success=False -> 跳过（SQL 报错不当死）。"""
        class FakeResult:
            success = False
            rows = []
            error = "relation does not exist"

        class FakeExecutor:
            def test_connection(self): return True
            def execute(self, sql): return FakeResult()
            def close(self): pass

        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                return FakeExecutor()

        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_join_key_check("dws", "dim", "dim_store", "store_id")
        assert "跳过试算" in out
        assert "relation does not exist" in out


# ============================================================
# read_target_schema：从 ts.json 取 target schema
# ============================================================

class TestReadTargetSchema:
    def test_reads_schema(self, tmp_path):
        ts = {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f"}}}}
        p = tmp_path / "ts.json"
        p.write_text(json.dumps(ts), encoding="utf-8")
        assert read_target_schema(str(p)) == "dws"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_target_schema("/nonexistent/ts.json")

    def test_no_schema_raises(self, tmp_path):
        ts = {"meta": {"target": {"f_table": {"table": "dwb_test_f"}}}}
        p = tmp_path / "ts.json"
        p.write_text(json.dumps(ts), encoding="utf-8")
        with pytest.raises(ValueError):
            read_target_schema(str(p))
