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
# 评估层 --eval（2026-09-17 整体化：草稿随 view 预置[shared/eval_workbench
# 同源生成] + stdin 答案合并 + 一次调用收口——每条路必然落到结果单）
# ============================================================

class TestExtractJoinFacts:
    """结构化条件机械提取（零猜测）：键/限定预填、取一信号、开窗 partition 提取。"""

    def test_structured_key_and_where(self):
        from eval_workbench import extract_join_facts
        f = extract_join_facts("f.cust_code=c1.code and c1.status='1' and f.x=1", "c1")
        assert f["structured"] is True
        assert f["key"] == "code"
        assert f["where"] == "status='1'"  # f.x=1 是主表限定，不进 c1 侧

    def test_composite_key(self):
        from eval_workbench import extract_join_facts
        f = extract_join_facts("f.a=c1.a and f.b=c1.b and c1.status=1", "c1")
        assert f["key"] == "a,b"

    def test_rn_treatment_signal(self):
        from eval_workbench import extract_join_facts
        f = extract_join_facts("f.x=c5.xx and c5.rn=1", "c5")
        assert f["treat_hit"] is True and "rn=1" in f["treat_signal"]
        assert f["key"] == "xx"  # rn=1 是处理标记不进键

    def test_partition_extraction(self):
        from eval_workbench import extract_join_facts
        cond = ("(select org_code, row_number() over(partition by org_code "
                "order by upd_time desc) rn from dim_org) org "
                "on f.org_code=org.org_code and org.rn=1")
        f = extract_join_facts(cond, "org")
        assert f["partition_cols"] == ["org_code"]
        assert f["key"] == "org_code"

    def test_natural_language_not_structured(self):
        from eval_workbench import extract_join_facts
        f = extract_join_facts("客户编码关联，取最新一条", "c2")
        assert f["structured"] is False and f["treat_hit"] is True

    def test_keyword_not_falsely_triggered(self):
        from eval_workbench import extract_join_facts
        assert extract_join_facts("最新版本的配置", "t")["treat_hit"] is False  # 词表收紧


class TestBuildEvalPlanData:
    """草稿数据（shared 生成器）：三区 + 预填/留?/机械核对——view 段与 --eval 同源。"""

    def _rs(self, tables, extra=None):
        rs = {"meta": {"target": {"f_table": {"schema": "zz", "table": "t_f"}}},
              "source_tables": tables, "field_mappings": []}
        rs.update(extra or {})
        return rs

    def test_zones_and_prefill(self):
        from eval_workbench import build_eval_plan_data
        d = build_eval_plan_data(self._rs([
            {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f", "join_condition": ""},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c1",
             "join_condition": "f.cust_code=c1.code and c1.status='1'"},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c2",
             "join_condition": "客户编码关联，状态有效"},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c3",
             "join_condition": "客户编码关联，取最新一条"},
        ], {"_db_verified": {"tables": ["ods.ods_f"]},
            "_condition_issues": [{"table": "ods.ods_f", "field": "xx", "issue": "引用无出处"}]}))
        run = {r["alias"]: r for r in d["run"]}
        assert run["f"]["prefilled"] is False and "主表/粒度证据线" in run["f"]["note"]
        assert run["c1"]["prefilled"] is True and run["c1"]["key"] == "code"
        assert run["c1"]["where"] == "status='1'"
        assert run["c2"]["prefilled"] is False and run["c2"]["key"] == ""  # 自然语言留 ?
        assert [t["alias"] for t in d["treat"]] == ["c3"]
        assert d["treat"][0]["check_ok"] is None  # 口径不全
        assert d["warn"] == [{"alias": "f", "field": "xx", "issue": "引用无出处"}]

    def test_mechanical_partition_check(self):
        from eval_workbench import build_eval_plan_data
        cond_ok = ("(select org_code, row_number() over(partition by org_code order by upd_time desc) rn "
                   "from dim_org) org on f.org_code=org.org_code and org.rn=1")
        cond_bad = ("(select org_code, row_number() over(partition by cust_id order by upd_time desc) rn "
                    "from dim_cust) c9 on f.org_code=c9.org_code and c9.rn=1")
        d = build_eval_plan_data(self._rs([
            {"source_schema": "ods", "source_table": "dim_org", "source_alias": "org", "join_condition": cond_ok},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c9", "join_condition": cond_bad},
        ]))
        by = {t["alias"]: t for t in d["treat"]}
        assert by["org"]["check_ok"] is True   # partition=关联键 机械核对一致
        assert by["c9"]["check_ok"] is False   # 不一致→处理后仍不唯一


class TestParseEvalLines:
    def test_forms_and_comments(self):
        from explore import parse_eval_lines
        items = parse_eval_lines("# 注释\n\n c1 | code | status='1' \nc2|k\no|ods.t|key|w=1\n坏")
        assert [(i["alias"], i["key"], i["where"]) for i in items[:3]] == \
            [("c1", "code", "status='1'"), ("c2", "k", ""), ("o", "key", "w=1")]
        assert items[3]["err"]

    def test_missing_key_flagged(self):
        from explore import parse_eval_lines
        assert parse_eval_lines("c1|")[0]["err"]


class TestRunEval:
    """--eval 合并语义：预填行自动跑 / ? 答案按别名合并 / 未答自动疑点 /
    免实测行事实行自动生成 / 存在性闸+唯一性实测（假执行器）。"""

    def _setup(self, tmp_path, tables, cache_tables, extra=None):
        rs = {"meta": {"target": {"f_table": {"schema": "zz", "table": "t_f"}}},
              "source_tables": tables, "field_mappings": []}
        rs.update(extra or {})
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

    def test_merge_semantics(self, tmp_path, monkeypatch):
        """预填行 stdin 不给也自动跑；? 答案按别名合并；免实测行事实行自动生成；
        cod_cf 形态（键不存在）闸拦进疑点。"""
        from explore import run_eval
        p = self._setup(tmp_path, [
            {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f", "join_condition": ""},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c1",
             "join_condition": "f.cust_code=c1.code and c1.status='1'"},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c2",
             "join_condition": "客户编码关联，状态有效"},
            {"source_schema": "ods", "source_table": "dim_org", "source_alias": "org",
             "join_condition": "(select org_code, row_number() over(partition by org_code "
                               "order by upd_time desc) rn from dim_org) org "
                               "on f.org_code=org.org_code and org.rn=1"},
        ], {"ods.ods_f": {"order_id": "i"},
            "ods.dim_cust": {"code_x": "v", "cust_code": "v", "cust_id": "i"},
            "ods.dim_org": {"org_code": "v"}})
        self._fake_db(monkeypatch, [
            ("FROM ods.ods_f", [{"total": 100, "distinct_cnt": 100}]),
            ("FROM ods.dim_cust", [{"total": 200, "distinct_cnt": 150}]),
            ("GROUP BY", [{"cust_code": "c_001", "dup_cnt": 3}]),
        ])
        out = run_eval(p, "zz", "f|order_id|\nc2|cust_code|\n")  # 只答 ? 行，预填行自动跑
        # 免实测行 → 事实行自动生成（机械核对一致）
        assert "免实测" in out and "机械核对一致" in out
        assert "- alias: org" in out and "输入声明取一处理" in out
        # 预填行 c1 自动跑：cod_cf 形态闸拦（code 不存在→疑点，不跑唯一性）
        assert "键字段不存在: code" in out and "不跑唯一性" in out and "相近" in out
        # ? 行答案合并：c2 实测不唯一 → 事实行+疑点
        assert "join_key_unique: false" in out and "重复 50" in out and "strategy:" in out
        # 主表答案：实测唯一 → 事实行
        assert "join_key_unique: true" in out and "100 行零重复" in out

    def test_unanswered_auto_doubt(self, tmp_path, monkeypatch):
        """? 未答=合法答案——自动进疑点草稿。"""
        from explore import run_eval
        p = self._setup(tmp_path, [
            {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f", "join_condition": ""},
            {"source_schema": "ods", "source_table": "dim_cust", "source_alias": "c2",
             "join_condition": "客户编码关联，状态有效"},
        ], {"ods.ods_f": {"order_id": "i"}, "ods.dim_cust": {"cust_code": "v"}})
        class FakeMod:
            @staticmethod
            def create_executor_for_schema(schema, role="etl"):
                raise RuntimeError("no db")
        monkeypatch.setitem(__import__("sys").modules, "dws_db", FakeMod)
        out = run_eval(p, "zz", "")  # 一行不答
        assert "未答" in out and "键未确定" in out
        assert "（无——评估层无疑点，直接进五层）" not in out

    def test_treat_alias_answer_ignored_and_unknown_alias(self, tmp_path):
        from explore import run_eval
        p = self._setup(tmp_path, [
            {"source_schema": "ods", "source_table": "ods_f", "source_alias": "f", "join_condition": ""},
            {"source_schema": "ods", "source_table": "dim_org", "source_alias": "org",
             "join_condition": "f.org_code=org.org_code and org.rn=1"},
        ], {"ods.ods_f": {"order_id": "i"}, "ods.dim_org": {"org_code": "v"}})
        out = run_eval(p, "zz", "org|org_code|\nzz9|x|\n")
        assert "免实测行忽略" in out       # 免实测行不接受回灌（声明依据已定）
        assert "不在 rs_input" in out      # 未知别名报错指路


class TestEvalCli:
    """CLI 级：--eval 端到端（heredoc 'N' 引号原样到达=通道级回归）、兜底草稿、
    全预填自动连跑、旧旗标退役。"""

    def _script(self):
        from pathlib import Path as _Path
        return _Path(__file__).resolve().parent.parent / "skills" / "dws-design" / "scripts" / "explore.py"

    def _fixture(self, tmp_path, tables):
        d = tmp_path / "_internal"
        d.mkdir()
        (d / "rs_input.json").write_text(json.dumps({
            "meta": {"target": {"f_table": {"schema": "zz_nodb", "table": "t_f"}}},
            "source_tables": tables, "field_mappings": []}, ensure_ascii=False), encoding="utf-8")
        (d / "schema_cache.json").write_text(json.dumps(
            {"cached_at": "2099-01-01T00:00:00",
             "tables": {"ods.t1": {"k": "bigint", "del_flag": "varchar"},
                        "ods.t2": {"kid": "bigint"}}}), encoding="utf-8")
        return d / "rs_input.json"

    def test_stdin_heredoc_quotes_survive(self, tmp_path):
        """'N' 经真实 bash heredoc 原样到达（内网 PS argv 剥引号问题的通道级替代证明）。"""
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path, [
            {"source_schema": "ods", "source_table": "t1", "source_alias": "c1",
             "join_condition": "客户编码关联，状态有效"}])
        cmd = (f"{_sys.executable} {self._script()} --rs {rs} --eval <<'EOF'\n"
               "c1|k|del_flag = 'N'\nEOF")
        r = _sp.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=60)
        combined = r.stdout + r.stderr
        assert "del_flag = 'N'" in combined, combined  # 引号完整回显=stdin 逐字到达
        assert "唯一性未实测" in combined  # zz_nodb 无数据源 → 未实测（确定性离线）

    def test_no_stdin_draft_fallback(self, tmp_path):
        """无 stdin=兜底出草稿（正常流程草稿随 view 预置；此处验能力）。"""
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path, [
            {"source_schema": "ods", "source_table": "t1", "source_alias": "c1",
             "join_condition": "客户编码关联，状态有效"}])
        r = _sp.run([_sys.executable, str(self._script()), "--rs", str(rs), "--eval"],
                    input="", capture_output=True, text=True, timeout=60)
        assert "评估清单" in r.stdout and "?" in r.stdout

    def test_all_prefilled_autorun(self, tmp_path):
        """零 ? 行（全结构化预填）→ 无 stdin 也当场连跑直接出结果单。"""
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path, [
            {"source_schema": "ods", "source_table": "t2", "source_alias": "c2",
             "join_condition": "f.kid=c2.kid and c2.status=1"}])
        r = _sp.run([_sys.executable, str(self._script()), "--rs", str(rs), "--eval"],
                    input="", capture_output=True, text=True, timeout=60)
        assert "结果单" in r.stdout            # 直接跑出结果单
        assert "唯一性未实测" in r.stdout      # zz_nodb → 未验证事实行
        assert "回灌" not in r.stdout          # 不是草稿

    def test_old_flags_retired(self, tmp_path):
        """--plan/--batch-stdin 已收编进 --eval——旧旗标 argparse 报错。"""
        import subprocess as _sp
        import sys as _sys
        rs = self._fixture(tmp_path, [])
        for old in ("--plan", "--batch-stdin"):
            r = _sp.run([_sys.executable, str(self._script()), "--rs", str(rs), old],
                        capture_output=True, text=True, timeout=60)
            assert r.returncode != 0

