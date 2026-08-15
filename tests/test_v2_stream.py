"""pipeline 流式子进程测试：成功回显 + 超时收割（僵死进程也能被杀）。"""

import sys
from pathlib import Path

import pytest

_V2_DIR = Path(__file__).resolve().parent.parent / "eval-suite" / "v2"
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

from pipeline import _run_stream


class TestRunStream:
    def test_success_returns_code_and_output(self, capsys):
        code, out = _run_stream([sys.executable, "-c", "print('hello-stream')"], timeout=10)
        assert code == 0
        assert "hello-stream" in out

    def test_timeout_kills_hung_process(self):
        code, out = _run_stream(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1
        )
        assert code == -1
        assert "超时" in out

    def test_nonzero_exit_propagates(self):
        code, out = _run_stream([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10)
        assert code == 3
