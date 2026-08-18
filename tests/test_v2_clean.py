"""跑前清场测试：防 AI 复用旧产出污染稳定性测量。"""

import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import run as run_mod


def _make_deliver(base: Path, asset: str) -> Path:
    d = base / "app1" / "sch1" / asset / "ddlc_design_dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ts.json").write_text("{}", encoding="utf-8")
    return d


class TestCleanDeliver:
    def test_removes_existing_deliver(self, tmp_path, monkeypatch, capsys):
        """正常清场：删掉 DELIVER_BASE 下的 ddlc_design_dev。"""
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path)
        d = _make_deliver(tmp_path, "dwb_x")
        run_mod._clean_deliver(d)
        assert not d.exists()
        assert "已清空" in capsys.readouterr().out

    def test_noop_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path)
        run_mod._clean_deliver(None)
        run_mod._clean_deliver(tmp_path / "不存在" / "ddlc_design_dev")

    def test_guardrail_rejects_outside_base(self, tmp_path, monkeypatch, capsys):
        """护栏：DELIVER_BASE 之外的 ddlc_design_dev 拒删。"""
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path / "deliver")
        outside = _make_deliver(tmp_path / "别的地方", "dwb_x")
        run_mod._clean_deliver(outside)
        assert outside.exists()  # 未被删
        assert "护栏" in capsys.readouterr().out

    def test_guardrail_rejects_wrong_dirname(self, tmp_path, monkeypatch, capsys):
        """护栏：目录名不是 ddlc_design_dev 的拒删（防误删资产层/其他目录）。"""
        monkeypatch.setattr(run_mod, "DELIVER_BASE", tmp_path)
        wrong = tmp_path / "app1" / "sch1" / "dwb_x" / "etl"
        wrong.mkdir(parents=True)
        run_mod._clean_deliver(wrong)
        assert wrong.exists()
        assert "护栏" in capsys.readouterr().out
