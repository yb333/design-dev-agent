"""pipeline 流式子进程测试：成功回显 + 超时收割（僵死进程也能被杀）。"""

import sys
from pathlib import Path

import pytest

_V2_DIR = Path(__file__).resolve().parent.parent / "eval-suite" / "v2"
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

import pipeline
from pipeline import _run_stream


class TestRunStream:
    def test_success_returns_code_and_output(self, capsys):
        code, out = _run_stream([sys.executable, "-c", "print('hello-stream')"], timeout=10)
        assert code == 0
        assert "hello-stream" in out

    def test_full_command_echoed(self, capsys):
        """执行窗口回显完整提交命令（含空格参数加引号）。"""
        _run_stream([sys.executable, "-c", "print('x')"], timeout=10)
        captured = capsys.readouterr().out
        assert "$ " in captured
        assert sys.executable in captured
        assert "-c" in captured

    def test_spaced_arg_quoted_in_echo(self, capsys):
        _run_stream([sys.executable, "-c", "print('y')"], timeout=10, )
        # 直接验证引号逻辑：含空格消息整体加引号
        from pipeline import _run_stream as rs
        rs(["echo", "hello world"], timeout=5, )
        captured = capsys.readouterr().out
        assert '"hello world"' in captured

    def test_timeout_kills_hung_process(self):
        code, out = _run_stream(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1
        )
        assert code == -1
        assert "超时" in out

    def test_nonzero_exit_propagates(self):
        code, out = _run_stream([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10)
        assert code == 3


class TestUtf8Passthrough:
    def test_chinese_output_decoded(self):
        """子进程 UTF-8 中文输出完整解码（Windows GBK 崩溃回归）。"""
        code, out = _run_stream([sys.executable, "-c", "print('中文输出测试✅')"], timeout=10)
        assert code == 0
        assert "中文输出测试" in out


class TestQuietVsVerbose:
    def test_quiet_does_not_print_child_lines(self, capsys):
        """安静模式：子进程行不上屏（全量仍进返回值），命令回显保留。"""
        pipeline.set_verbose(False)
        # marker 拼接产生：只出现在子进程输出，不出现在命令回显文本里
        _run_stream([sys.executable, "-c", "print('NO'+'ISY_MARKER')"], timeout=10, label="t")
        out = capsys.readouterr().out
        assert "NOISY_MARKER" not in out
        assert "$ " in out  # 命令回显仍是关键节点

    def test_verbose_prints_child_lines(self, capsys):
        pipeline.set_verbose(True)
        try:
            _run_stream([sys.executable, "-c", "print('NO'+'ISY_MARKER')"], timeout=10, label="t")
            out = capsys.readouterr().out
            assert "NOISY_MARKER" in out
        finally:
            pipeline.set_verbose(False)

    def test_output_returned_regardless_of_mode(self):
        pipeline.set_verbose(False)
        code, out = _run_stream([sys.executable, "-c", "print('PAYLOAD')"], timeout=10)
        assert "PAYLOAD" in out  # 安静≠丢失：全文在返回值里，失败时由 _fail_detail 展示


class TestLiveLog:
    def test_live_log_written_in_quiet(self, tmp_path, monkeypatch, capsys):
        """安静模式实时全文落盘（黑箱可打开查看），带 label 才开。"""
        import pipeline as pl

        pl.set_verbose(False)
        monkeypatch.setattr(pl, "_LIVE_DIR", tmp_path / "_live")
        _run_stream([sys.executable, "-c", "print('LIVE_PAYLOAD')"], timeout=10, label="designer")
        out = capsys.readouterr().out
        assert "实时全文可查看" in out  # 提示路径是关键节点信息
        live = tmp_path / "_live" / "designer.log"
        assert live.exists()
        assert "LIVE_PAYLOAD" in live.read_text(encoding="utf-8")

    def test_no_label_no_live_log(self, tmp_path, monkeypatch):
        import pipeline as pl

        monkeypatch.setattr(pl, "_LIVE_DIR", tmp_path / "_live")
        _run_stream([sys.executable, "-c", "print('x')"], timeout=10)
        assert not (tmp_path / "_live").exists()
