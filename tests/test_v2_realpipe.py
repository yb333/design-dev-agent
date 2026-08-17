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
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        deliver = _make_deliver(tmp_path / "base" / "dwb_x")

        calls = {}

        def fake_stream(cmd, timeout, cwd=None):
            calls["cmd"] = cmd
            return 0, ""

        def fake_find(base, name):
            return deliver if name == "dwb_x" else None

        monkeypatch.setattr(real_pipe, "_run_stream", fake_stream)
        monkeypatch.setattr(real_pipe, "find_deliver", fake_find)

        case_dir = tmp_path / "dwb_x"
        case_dir.mkdir()
        steps = real_pipe.run_real_pipe(case_dir, tmp_path / "base", timeout=5)
        assert len(steps) == 1
        assert steps[0].step == "new-pipe(真实流程)"
        assert steps[0].status.value == "pass"
        # 调用形态：--command new-pipe + 消息含 mapping 路径与非交互声明
        assert "--command" in calls["cmd"] and "new-pipe" in calls["cmd"]
        msg = calls["cmd"][-1]
        assert "mapping.xlsx" in msg and "非交互" in msg

    def test_fail_step_when_no_artifacts(self, tmp_path, monkeypatch):
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(real_pipe, "_run_stream", lambda cmd, t, cwd=None: (0, "ran ok"))
        monkeypatch.setattr(real_pipe, "find_deliver", lambda base, name: None)
        case_dir = tmp_path / "dwb_x"
        case_dir.mkdir()
        steps = real_pipe.run_real_pipe(case_dir, tmp_path / "base", timeout=5)
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
        with pytest.raises(RuntimeError, match="WinError 2"):
            pipeline.opencode_cmd()
