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
            "SELECT COUNT(1) AS total, COUNT(DISTINCT store_id) AS distinct_cnt "
            "FROM dim.dim_store"
        )

    def test_with_where(self):
        sql = build_join_key_sql("dim", "dim_store", "store_id", "is_current = 1")
        assert sql.endswith("WHERE is_current = 1")
        assert "COUNT(DISTINCT store_id)" in sql

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


# ============================================================
# 评估层作业台（2026-09-17：--plan 草稿 + --batch-stdin 行协议流水线）
# ============================================================

class TestExtractJoinFacts:
    """结构化条件机械提取（零猜测）：键/限定预填、取一信号、开窗 partition 提取。"""

    def test_structured_key_and_where(self):
        from explore import extract_join_facts
        f = extract_join_facts("f.cust_code=c1.code and c1.status='1' and f.x=1", "c1")
        assert f["structured"] is True
        assert f["key"] == "code"
        assert f["where"] == "status='1'"  # f.x=1 是主表限定，不进 c1 侧

    def test_composite_key(self):
        from explore import extract_join_facts
        f = extract_join_facts("f.a=c1.a and f.b=c1.b and c1.status=1", "c1")
        assert f["key"] == "a,b"

    def test_rn_treatment_signal(self):
        from explore import extract_join_facts
        f = extract_join_facts("f.x=c5.xx and c5.rn=1", "c5")
        assert f["treat_hit"] is True and "rn=1" in f["treat_signal"]
        assert f["key"] == "xx"  # rn=1 是处理标记不进键

    def test_partition_extraction(self):
        from explore import extract_join_facts
        cond = ("(select org_code, row_number() over(partition by org_code "
                "order by upd_time desc) rn from dim_org) org "
                "on f.org_code=org.org_code and org.rn=1")
        f = extract_join_facts(cond, "org")
        assert f["partition_cols"] == ["org_code"]
        assert f["key"] == "org_code"

    def test_natural_language_not_structured(self):
        from explore import extract_join_facts
        f = extract_join_facts("客户编码关联，取最新一条", "c2")
        assert f["structured"] is False and f["treat_hit"] is True

    def test_keyword_not_falsely_triggered(self):
        from explore import extract_join_facts
        assert extract_join_facts("最新版本的配置", "t")["treat_hit"] is False  # 词表收紧，"最新"单字不触发


class TestBuildEvalPlan:
    """plan 草稿：三区（需实测/已声明处理/输入存疑）+ 预填/留?/机械核对。"""

    def _rs(self, tmp_path, tables, extra=None):
        rs = {"meta": {"target": {"f_table": {"schema": "zz", "table": "t_f"}}},
              "source_tables": tables, "field_mappings": []}
        rs.update(extra or {})
        d = tmp_path / "_internal"
        d.mkdir(exist_ok=True)
        (d / "rs_input.json").write_text(json.dumps(rs, ensure_ascii=False), encoding="utf-8")
        return str(d / "rs_input.json")

    def test_zones_and_prefill(self, tmp_path):
        from explore import build_eval_plan
        p = self._rs(tmp_path, [
            {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f", "join_condition": ""},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c1",
             "join_condition": "f.cust_code=c1.code and c1.status='1'"},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c2",
             "join_condition": "客户编码关联，状态有效"},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c3",
             "join_condition": "客户编码关联，取最新一条"},
        ], {"_db_verified": {"tables": ["ods.ods_f"], "fields": 1, "via": "db"},
            "_condition_issues": [{"table": "ods.ods_f", "field": "xx", "issue": "引用无出处"}]})
        out = build_eval_plan(p)
        assert "f|?|?" in out and "主表/粒度证据线" in out and "precheck已核" in out
        assert "c1|code|status='1'" in out and "预填自结构化条件" in out
        assert "c2|?|?" in out and "客户编码关联，状态有效" in out  # 自然语言留 ?
        assert "已声明处理" in out and "口径不全=疑点上报" in out  # c3 取最新→免实测+口径核对
        assert "⚠ f/xx" in out

    def test_mechanical_partition_check(self, tmp_path):
        from explore import build_eval_plan
        cond_ok = ("(select org_code, row_number() over(partition by org_code order by upd_time desc) rn "
                   "from dim_org) org on f.org_code=org.org_code and org.rn=1")
        cond_bad = ("(select org_code, row_number() over(partition by cust_id order by upd_time desc) rn "
                    "from dim_cust) c9 on f.org_code=c9.org_code and c9.rn=1")
        p = self._rs(tmp_path, [
            {"source_schema": "ods", "source_table": "dim_org", "source_alias": "org", "join_condition": cond_ok},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c9", "join_condition": cond_bad},
        ])
        out = build_eval_plan(p)
        assert "机械核对一致 ✓" in out
        assert "处理后仍不唯一" in out  # partition by cust_id ≠ 关联键 org_code


class TestParseEvalLines:
    """行协议解析：别名|键|限定（兼容 2/4 字段形态、#注释、坏行报错）。"""

    def test_forms_and_comments(self):
        from explore import parse_eval_lines
        items = parse_eval_lines("# 注释\n\n c1 | code | status='1' \nc2|k\no|ods.t|key|w=1\n坏")
        assert [(i["alias"], i["key"], i["where"]) for i in items[:3]] == \
            [("c1", "code", "status='1'"), ("c2", "k", ""), ("o", "key", "w=1")]
        assert items[3]["err"]

    def test_missing_key_flagged(self):
        from explore import parse_eval_lines
        assert parse_eval_lines("c1|")[0]["err"]


class TestRunEvalBatch:
    """流水线三检查点：键不存在→疑点不跑唯一性 / 不唯一→事实行+疑点草稿 / 唯一→事实行。"""

    def _setup(self, tmp_path, cache_tables):
        rs = {"meta": {"target": {"f_table": {"schema": "zz", "table": "t_f"}}},
              "source_tables": [
                  {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c1"},
                  {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f"}],
              "field_mappings": []}
        d = tmp_path / "_internal"
        d.mkdir(exist_ok=True)
        (d / "rs_input.json").write_text(json.dumps(rs, ensure_ascii=False), encoding="utf-8")
        (d / "schema_cache.json").write_text(json.dumps(
            {"cached_at": "2099-01-01T00:00:00", "tables": cache_tables}), encoding="utf-8")
        return str(d / "rs_input.json")

    def _fake_db(self, monkeypatch, results):
        class FakeResult:
            success = True
            error = ""
            def __init__(self, rows):
                self.rows = rows
        class FakeExecutor:
            def test_connection(self):
                return True
            def execute(self, sql):
                for pat, rows in results:
                    if pat in sql:
                        return FakeResult(rows)
                return FakeResult([])
            def close(self):
                pass
        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                return FakeExecutor()
        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)

    def test_three_checkpoints(self, tmp_path, monkeypatch):
        from explore import run_eval_batch
        p = self._setup(tmp_path, {"ods.dim_cust": {"code_x": "v", "cust_code": "v", "cust_id": "i"},
                                   "ods.ods_f": {"order_id": "i"}})
        self._fake_db(monkeypatch, [
            ("FROM ods.ods_f", [{"total": 100, "distinct_cnt": 100}]),
            ("FROM ods.dim_cust", [{"total": 200, "distinct_cnt": 150}]),
            ("GROUP BY", [{"cust_id": "c_001", "dup_cnt": 3}]),
        ])
        out = run_eval_batch(p, "zz", "c1|code|status='1'\nf|order_id|\nc1|cust_id|\n")
        assert "键字段不存在: code" in out and "不跑唯一性" in out  # 检查点1（cod_cf 案例形态）
        assert "键字段 code 物理不存在" in out and "相近" in out  # 疑点草稿+相近名线索
        assert "join_key_unique: true" in out and "100 行零重复" in out  # 检查点2
        assert "join_key_unique: false" in out and "重复 50" in out  # 检查点3
        assert "strategy:" in out and "疑似方向" in out

    def test_dedupe(self, tmp_path, monkeypatch):
        from explore import run_eval_batch
        p = self._setup(tmp_path, {"ods.ods_f": {"order_id": "i"}})
        self._fake_db(monkeypatch, [("FROM ods.ods_f", [{"total": 5, "distinct_cnt": 5}])])
        out = run_eval_batch(p, "zz", "f|order_id|\nf|order_id|\n")
        assert "去重" in out and out.count("join_key_unique: true") == 1

    def test_db_down_marks_unverified_no_doubt(self, tmp_path, monkeypatch):
        from explore import run_eval_batch
        p = self._setup(tmp_path, {"ods.ods_f": {"order_id": "i"}})
        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                raise RuntimeError("no db")
        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_eval_batch(p, "zz", "f|order_id|")
        assert "唯一性未实测" in out and '"未验证"' in out
        assert "（无——评估层无疑点，直接进五层）" in out

    def test_alias_not_found_and_bad_line(self, tmp_path):
        from explore import run_eval_batch
        p = self._setup(tmp_path, {"ods.ods_f": {"order_id": "i"}})
        out = run_eval_batch(p, "zz", "zz9|foo|\n坏行\n")
        assert "不在 rs_input" in out and "行格式" in out


class TestEvalWorkbenchCli:
    """CLI 级端到端：bash heredoc 下 'N' 引号原样到达（通道级回归）+ --plan 离线
    + argv 内联 JSON 退役指针。"""

    def _script(self):
        from pathlib import Path as _Path
        return _Path(__file__).resolve().parent.parent / "skills" / "dws-design" / "scripts" / "explore.py"

    def _fixture(self, tmp_path):
        d = tmp_path / "_internal"
        d.mkdir()
        (d / "rs_input.json").write_text(json.dumps({
            "meta": {"target": {"f_table": {"schema": "zz_nodb", "table": "t_f"}}},
            "source_tables": [
                {"source_schema": "ods", "source_table": "t1", "source_alias": "c1",
                 "join_condition": "f.k=c1.k and c1.del_flag='N'"}],
            "field_mappings": []}, ensure_ascii=False), encoding="utf-8")
        (d / "schema_cache.json").write_text(json.dumps(
            {"cached_at": "2099-01-01T00:00:00",
             "tables": {"ods.t1": {"k": "bigint", "del_flag": "varchar"}}}), encoding="utf-8")
        return d / "rs_input.json"

    def test_stdin_heredoc_quotes_survive(self, tmp_path):
        """'N' 经真实 bash heredoc 原样到达（内网 PS argv 剥引号问题的通道级替代证明）。"""
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path)
        cmd = (f"{_sys.executable} {self._script()} --rs {rs} --batch-stdin <<'EOF'\n"
               "c1|k|del_flag = 'N'\nEOF")
        r = _sp.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=60)
        combined = r.stdout + r.stderr
        assert "del_flag = 'N'" in combined, combined  # 引号完整回显=stdin 逐字到达
        assert "唯一性未实测" in combined  # zz_nodb 无数据源 → 未实测（确定性离线）

    def test_plan_cli_offline(self, tmp_path):
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path)
        r = _sp.run([_sys.executable, str(self._script()), "--rs", str(rs), "--plan"],
                    capture_output=True, text=True, timeout=60)
        assert "评估清单草稿" in r.stdout
        assert "c1|k|del_flag='N'" in r.stdout  # 结构化预填直出

    def test_argv_inline_json_retired(self, tmp_path):
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path)
        r = _sp.run([_sys.executable, str(self._script()), "--rs", str(rs),
                     "--batch", '[{"tag":"c1"}]'],
                    capture_output=True, text=True, timeout=60)
        assert "argv 内联 JSON 已退役" in r.stdout
        assert "--batch-stdin" in r.stdout
