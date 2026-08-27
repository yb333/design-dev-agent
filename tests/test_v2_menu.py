"""菜单逐级返回测试：b 键返回上一级，不再只能 q 退出重来。"""

import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import menu


def _feed(monkeypatch, seq):
    """按序喂 input；耗尽后抛 StopIteration 让测试失败可见。"""
    it = iter(seq)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


class TestBackNavigation:
    def test_back_raises_in_ask_choice(self, monkeypatch):
        _feed(monkeypatch, ["b"])
        with pytest.raises(menu._Back):
            menu._ask_choice("选哪个", 3, allow_back=True)

    def test_back_disabled_without_flag(self, monkeypatch):
        _feed(monkeypatch, ["x", "2"])  # 无效输入后给合法值（b 不在提示里）
        assert menu._ask_choice("选哪个", 3) == 2

    def test_history_back_returns_to_main(self, monkeypatch):
        """主菜单[6]历史 → b 应回主菜单 → 再选7退出，全程不崩。"""
        _feed(monkeypatch, ["6", "b", "", "7"])  # 6=历史, b=返回, 回车, 7=退出
        assert menu.main() == 0

    def test_source_back_returns_to_main(self, monkeypatch):
        """跑评测 → 来源层 b → 回主菜单 → 退出。"""
        _feed(monkeypatch, ["1", "b", "7"])
        assert menu.main() == 0

    def test_scope_back_straight_to_main(self, monkeypatch):
        """范围层 b 直达主菜单（不再逐层重问来源）。"""
        _feed(monkeypatch, ["1", "2", "b", "7"])
        assert menu.main() == 0
