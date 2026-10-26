# -*- coding: utf-8 -*-
"""ut_opt / UT 内核测试（2026-10-26 统一 UT 重构：双跑对比退役、写路径走共享内核、
主键/审计全集、merge 幂等第二遍、无条件 MERGE fail loud、ALTER 逐句判定）。

mock 契约对齐（本轮教训核心）：FakeExecutor.execute 失败=返回 ExecuteResult(
success=False) **不抛异常**（对齐 dws_db 真实契约）——此前 mock 按异常假设造，
掩盖了 opt 侧的契约误解病灶。
"""
import json
from pathlib import Path

import pytest

from dws_db import ExecuteResult
from run_ut import execute_write_path, verify_merge_idempotent, wrap_write, run_ut_check

SQL_OK = "SELECT a.x AS x FROM ods.t a"


class FakeExecutor:
    """契约对齐 dws_db：execute 失败返回 success=False 不抛；fetch_all 失败抛。"""

    def __init__(self, fail_on=None, counts=None, dup_keys=None):
        self.fail_on = fail_on or {}      # {sql 子串: 报错文本}
        self.counts = counts or []        # COUNT 查询按调用序返回的行数列表
        self.dup_keys = dup_keys or []    # 主键 GROUP HAVING 返回的重复键行
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)
        for key, err in self.fail_on.items():
            if key in sql:
                return ExecuteResult(success=False, error=err)
        if sql.strip().upper().startswith("EXPLAIN"):
            return ExecuteResult(success=True, rows=[{"plan": "1 | Seq Scan | 10"}])
        if "HAVING COUNT(*) > 1" in sql:
            return ExecuteResult(success=True, rows=self.dup_keys)
        if "COUNT(*)" in sql:
            n = self.counts.pop(0) if self.counts else 10
            col = "cnt" if "AS cnt" in sql else "N"   # 对齐查询别名
            return ExecuteResult(success=True, rows=[{col: n}])
        if "IS NULL" in sql:
            return ExecuteResult(success=True, rows=[{"N": 0}])
        return ExecuteResult(success=True, rowcount=10)

    def fetch_all(self, sql):
        r = self.execute(sql)          # 委托同一路由（对齐 dws_db.fetch_all 实现）
        if not r.success:
            raise RuntimeError(r.error)
        return list(r.rows or [])


class TestExecuteWritePath:
    """UT 写路径内核（opt 契约病灶的根治位）：预处理+拼装+判定分流。"""

    FIELDS = [{"target_field": "x", "field_type": "int"}]

    def test_pass_with_truncate_prep(self):
        ex = FakeExecutor()
        wp = execute_write_path(ex, "R1", "dws.t1", SQL_OK, self.FIELDS, "truncate_table")
        assert wp["status"] == "PASS"
        assert any("TRUNCATE" in s.upper() for s in ex.executed)   # 写前清理在（重跑无残留）
        assert any("INSERT" in s.upper() for s in ex.executed)

    def test_insert_failure_reported_not_swallowed(self):
        """execute 失败（返回 success=False 不抛）→ 必须报 FAIL——2026-10-26 病灶回归锁。"""
        ex = FakeExecutor(fail_on={"INSERT": "ERROR: column \"y\" does not exist"})
        wp = execute_write_path(ex, "R1", "dws.t1", SQL_OK, self.FIELDS, "truncate_table")
        assert wp["status"] == "FAIL"
        assert wp["error_type"] == "SQL"          # COLUMN/DOES NOT EXIST 关键词分流
        assert "does not exist" in wp["detail"]

    def test_env_failure_routed(self):
        ex = FakeExecutor(fail_on={"INSERT": "permission denied"})
        wp = execute_write_path(ex, "R1", "dws.t1", SQL_OK, self.FIELDS, "truncate_table")
        assert wp["status"] == "FAIL" and wp["error_type"] == "ENV"

    def test_prep_failure_reported(self):
        ex = FakeExecutor(fail_on={"TRUNCATE": "relation does not exist"})
        wp = execute_write_path(ex, "R1", "dws.t1", SQL_OK, self.FIELDS, "truncate_table")
        assert wp["status"] == "FAIL" and "写前清理失败" in wp["detail"]

    def test_merge_without_condition_fails_loud(self):
        """merge 无 write_condition → 构造失败（wrap_write fail loud——旧 1=1 静默
        兜底在空表 UT 上跑得过、生产是交叉匹配灾难）。"""
        ex = FakeExecutor()
        wp = execute_write_path(ex, "R1", "dws.t1", SQL_OK, self.FIELDS, "merge_into", "")
        assert wp["status"] == "FAIL"
        assert "write_condition" in wp["detail"]


class TestMergeIdempotent:
    """merge 族幂等第二遍：同语句两遍行数不变=WHEN MATCHED 覆盖+重跑安全。"""

    MERGE_SQL = ("MERGE INTO dws.t1 T USING (SELECT 1 AS x) T1 ON T.x=T1.x "
                 "WHEN NOT MATCHED THEN INSERT (x) VALUES (T1.x)")

    def test_idempotent_pass(self):
        ex = FakeExecutor(counts=[10, 10])
        r = verify_merge_idempotent(ex, "R1", "dws.t1", self.MERGE_SQL)
        assert r["status"] == "PASS"
        assert "MATCHED" in r["detail"]
        assert sum(1 for s in ex.executed if "MERGE" in s.upper()) == 1  # 第二遍真执行

    def test_row_duplication_fails(self):
        ex = FakeExecutor(counts=[10, 23])
        r = verify_merge_idempotent(ex, "R1", "dws.t1", self.MERGE_SQL)
        assert r["status"] == "FAIL"
        assert "幂等性破坏" in r["detail"]

    def test_second_run_error_fails(self):
        ex = FakeExecutor(counts=[10], fail_on={"MERGE": "syntax error"})
        r = verify_merge_idempotent(ex, "R1", "dws.t1", self.MERGE_SQL)
        assert r["status"] == "FAIL" and "第二遍" in r["detail"]


class TestWrapWriteConditionGuard:
    def test_merge_no_condition_raises(self):
        with pytest.raises(ValueError, match="write_condition"):
            wrap_write(SQL_OK, "dws.t1", [{"target_field": "x"}], "merge_into", "", {"x"})


class TestApplyAltersVerdict:
    """ALTER 逐句判定（类型 MODIFY 转换失败当场爆——不再静默吞掉带病跑写路径）。"""

    def test_alter_failure_raises(self, tmp_path):
        from ut_opt import apply_alters
        ddl = tmp_path / "alter_table_t1.sql"
        ddl.write_text("ALTER TABLE dws.t1 MODIFY (x varchar(128));", encoding="utf-8")
        ex = FakeExecutor(fail_on={"MODIFY": "value too long"})
        with pytest.raises(RuntimeError, match="ALTER 失败"):
            apply_alters(ex, tmp_path, ["t1"], "dws")


class TestUtCheckFullSet:
    """资产数据检查全集（豁免移除）：主键重复必须被抓——口径修改后主键唯一性
    不被任何 diff 机制蕴含（UT 是资产质量门不是 diff 门）。"""

    def test_duplicate_primary_key_fails(self):
        ex = FakeExecutor(dup_keys=[{"x": "1", "cnt": 2}])
        checks = run_ut_check(ex, "dws.t1", ["x"], {"del_flag": {}})
        pk = [c for c in checks if c["check"] == "业务主键唯一"]
        assert pk and pk[0]["status"] == "FAIL"

    def test_clean_primary_key_passes(self):
        ex = FakeExecutor()   # 默认行数 10 >0 PASS / 主键无重复 / 审计空集
        checks = run_ut_check(ex, "dws.t1", ["x"], {})
        assert all(c["status"] != "FAIL" for c in checks), checks


class TestNewColumnNulls:
    def test_all_null_flags_join_miss(self, tmp_path):
        """全 NULL → 疑似新 JOIN 关联不上信号（LEFT JOIN 常态形态）。"""
        from ut_opt import check_new_column_nulls

        class NullEx:
            def fetch_all(self, sql):
                assert "null_channel_name" in sql
                return [{"total": 100, "null_channel_name": 100}]

        ts = {"change": {"fields": [
            {"field": "channel_name", "target_table": "dwb_x_d"}]}}
        out = check_new_column_nulls(NullEx(), ts, "dws")
        assert out[0]["nulls"] == 100 and out[0]["total"] == 100
        assert "关联不上" in out[0]["note"]

    def test_partial_null_and_clean(self, tmp_path):
        from ut_opt import check_new_column_nulls

        class NullEx:
            def __init__(self, ret):
                self.ret = ret
            def fetch_all(self, sql):
                return [self.ret]

        ts = {"change": {"fields": [{"field": "c1", "target_table": "t1"}]}}
        # 半数 NULL：过半提示
        out = check_new_column_nulls(NullEx({"total": 10, "null_c1": 6}), ts, "dws")
        assert "过半" in out[0]["note"]
        # 干净：无提示
        out2 = check_new_column_nulls(NullEx({"total": 10, "null_c1": 0}), ts, "dws")
        assert out2[0]["note"] == ""


class TestFenceStalenessGate:
    """围栏时效闸门：SQL 晚于围栏结果 = 过期，UT 拒跑（回路铁律机器化）。"""

    def _run_main(self, tmp_path, fence_exists=True, stale=False):
        import os, time
        etl = tmp_path / "etl"; etl.mkdir(exist_ok=True)
        (etl / "R0002.sql").write_text("SELECT 1", encoding="utf-8")
        internal = tmp_path / "_internal"
        if fence_exists:
            internal.mkdir(exist_ok=True)
            fr = internal / "sql_fence_result.json"
            fr.write_text('{"passed": true}', encoding="utf-8")
            if stale:
                past = time.time() - 100
                os.utime(etl / "R0002.sql", (time.time() + 50, time.time() + 50))
        ts_path = tmp_path / "ts_v2.json"
        ts_path.write_text(json.dumps(self._ts()), encoding="utf-8")
        from ut_opt import main
        return main(["--ts", str(ts_path), "--etl-dir", str(etl), "--baseline-dir", str(tmp_path),
                     "--ddl-dir", str(tmp_path), "--report", str(tmp_path / "r.md")])

    def _ts(self):
        return {"change": {"fields": [{"field": "b", "target_table": "t1"}]},
                "meta": {"target": {"f_table": {"schema": "dws", "table": "t1"}}}}

    def test_missing_fence_result_exit_2(self, tmp_path):
        assert self._run_main(tmp_path, fence_exists=False) == 2

    def test_stale_fence_exit_2(self, tmp_path):
        assert self._run_main(tmp_path, fence_exists=True, stale=True) == 2
