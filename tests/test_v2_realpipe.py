"""真实入口执行层测试：消息构造/非交互声明/产出判定/执行方式选择。"""

import json
import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pipeline
import real_pipe
import run as run_mod
from run import select_executor


def _make_deliver(tmp_path: Path) -> Path:
    deliver = tmp_path / "ddlc_design_dev"
    (deliver / "etl").mkdir(parents=True)
    (deliver / "ts.json").write_text("{}", encoding="utf-8")
    (deliver / "etl" / "R0001.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    return deliver


class TestBuildCommandArgs:
    def test_mapping_always_rs_when_exists(self, tmp_path):
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        (tmp_path / "RS.md").write_text("x", encoding="utf-8")
        args = real_pipe.build_command_args(tmp_path)
        assert len(args) == 2
        assert args[0].endswith("mapping.xlsx")
        assert args[1].endswith("RS.md")

    def test_mapping_only_without_rs(self, tmp_path):
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        args = real_pipe.build_command_args(tmp_path)
        assert len(args) == 1
        assert args[0].endswith("mapping.xlsx")

    def test_nonstandard_filenames_discovered(self, tmp_path):
        """非标准文件名（xx资产mapping.xlsx / RS需求文档.md）也能正确入参。"""
        (tmp_path / "订单中心资产mapping.xlsx").write_text("x", encoding="utf-8")
        (tmp_path / "RS需求文档.md").write_text("x", encoding="utf-8")
        args = real_pipe.build_command_args(tmp_path)
        assert len(args) == 2
        assert args[0].endswith("订单中心资产mapping.xlsx")
        assert args[1].endswith("RS需求文档.md")

    def test_raises_when_no_mapping(self, tmp_path):
        (tmp_path / "无关文件.txt").write_text("x", encoding="utf-8")
        with pytest.raises(RuntimeError, match="mapping"):
            real_pipe.build_command_args(tmp_path)

    def test_mapping_only_when_rs_absent(self, tmp_path):
        """目录里没有 RS 类文件 → 只传 mapping（无RS模式）。"""
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        args = real_pipe.build_command_args(tmp_path)
        assert len(args) == 1

    def test_non_interactive_clause_declares_eval(self):
        """非交互声明必须显式（new-pipe.md 闸口的唯一合法跳过条件）。"""
        assert "非交互" in real_pipe.NON_INTERACTIVE_CLAUSE
        assert "评测" in real_pipe.NON_INTERACTIVE_CLAUSE


class TestJudgeRealRun:
    def test_pass_with_ts_and_select(self, tmp_path):
        deliver = _make_deliver(tmp_path)
        ok, detail = real_pipe.judge_real_run(deliver, 0, "")
        assert ok and "1条SELECT" in detail

    def test_fail_when_no_deliver(self):
        ok, detail = real_pipe.judge_real_run(None, 0, "some output")
        assert not ok and "未找到产出目录" in detail

    def test_fail_when_ts_missing(self, tmp_path):
        deliver = tmp_path / "ddlc_design_dev"
        (deliver / "etl").mkdir(parents=True)
        (deliver / "etl" / "R0001.sql").write_text("SELECT 1", encoding="utf-8")
        ok, detail = real_pipe.judge_real_run(deliver, 0, "")
        assert not ok

    def test_fail_when_nonzero_exit(self, tmp_path):
        deliver = _make_deliver(tmp_path)
        ok, _ = real_pipe.judge_real_run(deliver, 1, "boom")
        assert not ok


class TestSelectExecutor:
    def test_real_by_default(self):
        assert select_executor(replay=False, skip_ai=False) == "real"

    def test_replay_flag(self):
        assert select_executor(replay=True, skip_ai=False) == "replay"

    def test_skip_ai_implies_replay(self):
        """--skip-ai 只在重放模式有意义 → 自动降级 replay。"""
        assert select_executor(replay=False, skip_ai=True) == "replay"


class TestRunRealPipe:
    def test_single_step_result(self, tmp_path, monkeypatch):
        """打桩 _run_stream + find_deliver：返回单步 PipelineStepResult。"""
        (tmp_path / "dwb_x").mkdir(exist_ok=True)
        (tmp_path / "dwb_x" / "mapping.xlsx").write_text("x", encoding="utf-8")
        deliver = _make_deliver(tmp_path / "base" / "dwb_x")

        calls = {}

        def fake_stream(cmd, timeout, cwd=None, label="", stage_provider=None, line_hook=None):
            calls["cmd"] = cmd
            return 0, ""

        def fake_find(base, name):
            return deliver if name == "dwb_x" else None

        monkeypatch.setattr(real_pipe, "_run_stream", fake_stream)
        monkeypatch.setattr(real_pipe, "find_deliver", fake_find)

        case_dir = tmp_path / "dwb_x"
        steps, stage_times, stage_loops = real_pipe.run_real_pipe(case_dir, tmp_path / "base", timeout=5)
        assert len(steps) == 1
        assert isinstance(stage_times, dict) and isinstance(stage_loops, dict)
        assert steps[0].step == "new-pipe(真实流程)"
        assert steps[0].status.value == "pass"
        # 调用形态：--command new-pipe + 消息含 mapping 路径与非交互声明
        assert "--command" in calls["cmd"] and "new-pipe" in calls["cmd"]
        msg = calls["cmd"][-1]
        assert "mapping.xlsx" in msg and "非交互" in msg

    def test_fail_step_when_no_artifacts(self, tmp_path, monkeypatch):
        (tmp_path / "dwb_x").mkdir(exist_ok=True)
        (tmp_path / "dwb_x" / "mapping.xlsx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(real_pipe, "_run_stream", lambda cmd, t, cwd=None, label="", stage_provider=None, line_hook=None: (0, "ran ok"))
        monkeypatch.setattr(real_pipe, "find_deliver", lambda base, name: None)
        case_dir = tmp_path / "dwb_x"
        steps, _, _ = real_pipe.run_real_pipe(case_dir, tmp_path / "base", timeout=5)
        assert steps[0].status.value == "fail"


class TestOpencodeCmd:
    """Windows 坑修复：opencode.cmd 的 Popen 解析（WinError 2）。"""

    def setup_method(self):
        pipeline._OPENCODE_RESOLVED = None  # 清缓存

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("EVAL_OPENCODE", "C:/xx/npm/opencode.cmd")
        assert pipeline.opencode_cmd() == ["C:/xx/npm/opencode.cmd"]

    def test_which_resolves(self, monkeypatch):
        monkeypatch.delenv("EVAL_OPENCODE", raising=False)
        monkeypatch.setattr(pipeline.shutil, "which", lambda name: "/usr/local/bin/opencode")
        assert pipeline.opencode_cmd() == ["/usr/local/bin/opencode"]

    def test_not_found_raises_with_hint(self, monkeypatch):
        monkeypatch.delenv("EVAL_OPENCODE", raising=False)
        monkeypatch.setattr(pipeline.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="未找到 agent 启动器"):
            pipeline.opencode_cmd()

    def test_nga_preferred_over_opencode(self, monkeypatch):
        """内网包壳 nga 优先于标准 opencode。"""
        monkeypatch.delenv("EVAL_OPENCODE", raising=False)
        monkeypatch.setattr(
            pipeline.shutil, "which",
            lambda name: {"nga": "/usr/bin/nga", "opencode": "/usr/bin/opencode"}.get(name))
        assert pipeline.opencode_cmd() == ["/usr/bin/nga"]


class TestReplayDeliverResolve:
    """重放模式无既有产出时的三层目录推导。"""

    def _fake_preprocess(self, tmp_path):
        """造假 _preprocess：往暂存目录写 rs_input（schema=sch1）。"""
        def fake(staging, mapping, rs, timeout):
            internal = staging / "_internal"
            internal.mkdir(parents=True, exist_ok=True)
            import json as j
            (internal / "rs_input.json").write_text(j.dumps(
                {"meta": {"target": {"f_table": {"schema": "sch1", "table": "dwb_x"}}}}),
                encoding="utf-8")
            return True, "ok"
        return fake

    def test_resolves_three_level_path(self, tmp_path, monkeypatch):
        case = tmp_path / "dwb_x"
        case.mkdir()
        (case / "mapping.xlsx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(pipeline, "_preprocess", self._fake_preprocess(tmp_path))
        monkeypatch.setattr(run_mod, "_resolve_appid_quiet", lambda schema: "APP1" if schema == "sch1" else "")
        deliver = run_mod._resolve_replay_deliver(case, "dwb_x", 5)
        assert deliver == tmp_path / "APP1" / "sch1" / "dwb_x" / "ddlc_design_dev"
        assert (deliver / "_internal" / "rs_input.json").exists()

    def test_raises_when_appid_unresolvable(self, tmp_path, monkeypatch):
        case = tmp_path / "dwb_x"
        case.mkdir()
        (case / "mapping.xlsx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(pipeline, "_preprocess", self._fake_preprocess(tmp_path))
        monkeypatch.setattr(run_mod, "_resolve_appid_quiet", lambda schema: "")
        with pytest.raises(RuntimeError, match="schema_apps"):
            run_mod._resolve_replay_deliver(case, "dwb_x", 5)

    def test_prepare_skips_real(self, tmp_path):
        """真实入口不做推导（new-pipe 自建目录）。"""
        out = run_mod._prepare_deliver_for(None, "real", tmp_path, "dwb_x", 5)
        assert "_未定位" in str(out)

    def test_prepare_replay_creates_dir(self, tmp_path, monkeypatch):
        case = tmp_path / "dwb_x"
        case.mkdir()
        monkeypatch.setattr(
            run_mod, "_resolve_replay_deliver",
            lambda c, n, t: tmp_path / "APP1" / "sch1" / n / "ddlc_design_dev")
        out = run_mod._prepare_deliver_for(None, "replay", case, "dwb_x", 5)
        assert out.exists()


class TestStageWatcher:
    """产出文件观察器：阶段反推 + 耗时推导。"""

    def test_find_deliver_loose_without_ts(self, tmp_path):
        """宽松定位：目录存在即可（ts.json 未生成也能找到）。"""
        d = tmp_path / "app" / "sch" / "dwb_x" / "ddlc_design_dev"
        d.mkdir(parents=True)
        assert real_pipe._find_deliver_loose(tmp_path, "dwb_x") == d

    def test_stage_text_follows_latest_marker(self, tmp_path):
        w = real_pipe._StageWatcher("dwb_x", tmp_path)
        try:
            deliver = tmp_path / "app" / "sch" / "dwb_x" / "ddlc_design_dev"
            (deliver / "_internal").mkdir(parents=True)
            (deliver / "_internal" / "rs_input.json").write_text("{}", encoding="utf-8")
            w._poll_once()
            assert "预处理" in w.stage_text()
            (deliver / "ts.json").write_text("{}", encoding="utf-8")
            w._poll_once()
            assert w.stage_text() == "TS组装"
            (deliver / "etl").mkdir()
            (deliver / "etl" / "R0001.sql").write_text("SELECT 1", encoding="utf-8")
            w._poll_once()
            assert w.stage_text() == "规则编码(1个SQL)"
        finally:
            w.finish()

    def test_finish_derives_durations(self, tmp_path):
        import time as _t
        w = real_pipe._StageWatcher("dwb_x", tmp_path)
        deliver = tmp_path / "app" / "sch" / "dwb_x" / "ddlc_design_dev"
        (deliver / "_internal").mkdir(parents=True)
        (deliver / "_internal" / "rs_input.json").write_text("{}", encoding="utf-8")
        w._poll_once()
        _t.sleep(0.05)
        (deliver / "ts.json").write_text("{}", encoding="utf-8")
        w._poll_once()
        times = w.finish()
        assert "预处理" in times and "TS组装" in times
        assert times["预处理"] >= 0.03  # 两个 marker 之间的间隔成了预处理阶段耗时


class TestStageTracker:
    """L2 流锚点状态机：阶段推进 + 回路计数 + 耗时时间线。"""

    def test_advance_by_anchors(self):
        t = real_pipe._StageTracker()
        t.feed("Running bash: python SHARED_SCRIPTS/preprocess.py --mapping x.xlsx\n")
        assert t.stage_text() == "预处理"
        t.feed("Task(subagent_type='dws-designer' ...)\n")
        assert t.stage_text() == "设计"
        t.feed("Running bash: python SHARED_SCRIPTS/assemble_ts.py --rs ...\n")
        assert t.stage_text() == "TS组装"

    def test_specific_anchor_wins_on_same_line(self):
        """assemble_ts 命令行含 design_decisions 路径——具体锚点（TS组装）优先。"""
        t = real_pipe._StageTracker()
        t.feed("python assemble_ts.py --decisions _internal/design_decisions.yaml\n")
        assert t.stage_text() == "TS组装"

    def test_loop_counted_on_revisit(self):
        """UT 后再现 dws-coder = 执行回路，显示(第2次·回路)。"""
        t = real_pipe._StageTracker()
        t.feed("dws-coder task for R0001\n")
        t.feed("python ut_precheck.py\n")
        assert t.stage_text() == "UT执行"
        t.feed("dws-coder 恢复会话修复 R0001\n")
        assert t.stage_text() == "规则编码(第2次·回路)"

    def test_finish_aggregates_loop_time_into_stage(self):
        import time as _t
        t = real_pipe._StageTracker()
        t.feed("python preprocess.py\n")
        _t.sleep(0.05)
        t.feed("dws-coder R0001\n")
        _t.sleep(0.05)
        t.feed("python ut_execute.py\n")
        _t.sleep(0.05)
        t.feed("dws-coder 修复\n")  # 回路：编码第二次
        _t.sleep(0.05)
        t.feed("python assemble_export.py\n")
        times, loops = t.finish()
        assert loops["规则编码"] == 2
        # 两次编码区段（0.05+0.05）都归编码——应明显大于单区段的预处理
        assert times["规则编码"] > times["预处理"] * 1.5

    def test_fallback_when_stream_blind(self):
        """流锚点全程没匹配 → 兜底文件观察器。"""
        t = real_pipe._StageTracker(fallback=None)
        t.feed("totally unrecognized output\n")
        times, loops = t.finish()
        assert times == {} and loops == {}


class TestParallelGroupStages:
    """编码段并行组（new-pipe 4a/4b/4c）：DDL/DQ/规则编码共存不互吞。"""

    def test_parallel_window_display(self):
        t = real_pipe._StageTracker()
        t.feed("python dispatch_plan.py --ts ts.json\n")
        assert t.stage_text() == "执行计划"
        t.feed("python assemble_ddl.py --ts ts.json\n")       # 4a 先出
        assert t.stage_text() == "DDL生成"
        t.feed("Task(subagent_type='dws-coder' R0001)\n")      # 4b 并行加入
        assert "规则编码" in t.stage_text() and "DDL生成" in t.stage_text()
        assert "(并行)" in t.stage_text()
        t.feed("产出 DQ SQL 到 /x/dq/\n")                       # 4c 也加入
        text = t.stage_text()
        assert "DQ生成" in text and "规则编码" in text and "DDL生成" in text
        # 顺序按流水线序
        assert text.index("DDL生成") < text.index("DQ生成") < text.index("规则编码")

    def test_serial_stage_closes_parallel_window(self):
        t = real_pipe._StageTracker()
        t.feed("assemble_ddl.py\n")
        t.feed("dws-coder R0001\n")
        t.feed("python check_db.py\n")  # UT探活=串行阶段，关掉并行组
        assert t.stage_text() == "UT探活"

    def test_parallel_durations_overlap_ok(self):
        """并行段各阶段各算各的活跃窗口（真并行，允许总和>墙钟）。"""
        import time as _t
        t = real_pipe._StageTracker()
        t.feed("assemble_ddl.py\n")          # DDL t0
        _t.sleep(0.03)
        t.feed("dws-coder R0001\n")          # coder t0=+0.03
        _t.sleep(0.06)
        t.feed("python check_db.py\n")       # t=0.09 关组：DDL 0.09, coder 0.06
        _t.sleep(0.01)
        times, _ = t.finish()
        assert abs(times["DDL生成"] - times["规则编码"] - 0.03) < 0.02

    def test_loop_back_after_parallel_closed(self):
        """UT后回coder：并行组清空后再到达=回路计数。"""
        t = real_pipe._StageTracker()
        t.feed("dws-coder R0001\n")
        t.feed("python ut_execute.py\n")
        t.feed("dws-coder 修复R0001\n")
        assert "第2次·回路" in t.stage_text()

    def test_dq_anchor(self):
        t = real_pipe._StageTracker()
        t.feed("dq_rules 非空，调 dws-coder 产出 DQ SQL 到 deliver/dq/\n")
        assert "DQ生成" in t.stage_text()


class TestDualSignalStages:
    """双信号合并回归：subagent 内层活动（设计/编码）顶层流不可见，靠文件 marker 补。

    用户实测症状：流锚点只命中顶层脚本（预检→执行计划→DDL），设计和编码被吞。
    """

    def test_design_recovered_by_file_marker(self):
        t = real_pipe._StageTracker()
        t.feed("python precheck.py\n")                       # 顶层流：预检
        assert t.stage_text() == "预检"
        t.feed_file("设计")                                    # designer 写了 decisions（流里看不到）
        assert t.stage_text() == "设计"                        # 不再被吞
        t.feed_file("TS组装")                                  # designer 内部跑了 assemble_ts
        assert t.stage_text() == "TS组装"
        t.feed("python dispatch_plan.py\n")                  # 顶层流推进
        assert t.stage_text() == "执行计划"

    def test_parallel_via_stream_ddl_plus_file_coder(self):
        t = real_pipe._StageTracker()
        t.feed("python dispatch_plan.py\n")
        t.feed("python assemble_ddl.py\n")                   # 顶层流：DDL（4a）
        assert t.stage_text() == "DDL生成"
        t.feed_file("规则编码")                                 # coder 写了 etl（流里看不到）
        text = t.stage_text()
        assert "DDL生成" in text and "规则编码" in text and "(并行)" in text

    def test_late_file_marker_no_regression(self):
        """滞后文件事件不许回退：预检阶段轮询到晚到的 rs_input 忽略。"""
        t = real_pipe._StageTracker()
        t.feed("python precheck.py\n")
        t.feed_file("预处理")   # rank 0 ≤ 预检 rank 1 → 忽略
        assert t.stage_text() == "预检"
        assert t.finish()[1].get("预处理", 0) == 0  # 没进活动集

    def test_stream_regression_counts_loop_but_file_cannot(self):
        """真实回路（类型风险重跑 precheck）由流锚点计数；文件事件永不制造假回路。"""
        t = real_pipe._StageTracker()
        t.feed("python precheck.py\n")
        t.feed("TYPE_RISK_PENDING {...}\n")          # 类型风险决策
        t.feed("python precheck.py\n")               # 剧本1b重跑=真实回路
        assert t.stage_text() == "预检(第2次·回路)"
        t.feed_file("设计")                            # 文件事件只前进
        assert t.stage_text() == "设计"
