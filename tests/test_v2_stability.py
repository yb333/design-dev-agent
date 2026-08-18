"""稳定性报告测试：快照聚合 + 断言分类 + golden 命中分布解析。"""

import json
import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import baseline
import stability


def _write_snap(case_dir: Path, ts: str, checks: list[dict], steps: list[dict] | None = None):
    d = case_dir / ts.replace(":", "-")
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(
        json.dumps({
            "case_name": case_dir.name,
            "timestamp": ts,
            "git_sha": "abc",
            "layer_stats": {},
            "pipeline_steps": steps or [],
            "checks": checks,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _chk(layer, key, status, detail=""):
    return {"layer": layer, "key": key, "status": status, "detail": detail or f"{key}: ok"}


class TestLoadRecent:
    def test_load_last_n_sorted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        _write_snap(case_dir, "2026-08-15T10:00:00", [_chk("artifacts", "ts.json", "pass")])
        _write_snap(case_dir, "2026-08-15T11:00:00", [_chk("artifacts", "ts.json", "fail")])
        _write_snap(case_dir, "2026-08-15T12:00:00", [_chk("artifacts", "ts.json", "pass")])
        snaps = stability.load_recent_snapshots("t", 2)
        assert len(snaps) == 2
        assert snaps[0]["timestamp"] == "2026-08-15T11:00:00"

    def test_empty_when_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        assert stability.load_recent_snapshots("nope", 5) == []


class TestClassify:
    def test_stable_pass_fail_flaky(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        for i in range(1, 5):
            checks = [
                _chk("artifacts", "ts.json", "pass"),          # 4/4 稳定过
                _chk("design", "load_mode", "fail"),            # 0/4 稳定挂
                _chk("design", "business_key",
                     "pass" if i % 2 == 1 else "fail"),         # 2/4 摇摆
            ]
            _write_snap(case_dir, f"2026-08-15T1{i}:00:00", checks)
        snaps = stability.load_recent_snapshots("t", 4)
        rows = stability.classify_assertions(snaps)["rows"]
        by_key = {r["key"]: r for r in rows}
        assert by_key["ts.json"]["class"] == "stable_pass"
        assert by_key["load_mode"]["class"] == "stable_fail"
        assert by_key["business_key"]["class"] == "flaky"
        assert by_key["business_key"]["pass"] == 2


class TestGoldenDistribution:
    def test_parse_hit_and_miss(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        _write_snap(case_dir, "2026-08-15T10:00:00", [
            _chk("golden", "命中", "pass", "命中 golden: 方案A")])
        _write_snap(case_dir, "2026-08-15T11:00:00", [
            _chk("golden", "未命中", "fail", "未命中任何 golden（越界，待人工裁决）— x")])
        _write_snap(case_dir, "2026-08-15T12:00:00", [
            _chk("golden", "无", "skip", "无 golden（未沉淀标准答案）")])
        snaps = stability.load_recent_snapshots("t", 3)
        assert stability._golden_status(snaps[0]) == "方案A"
        assert stability._golden_status(snaps[1]) == "未命中"
        assert stability._golden_status(snaps[2]) == "无golden"
        report = stability.render_stability("t", snaps)
        assert "稳定性报告" in report
        assert "方案A: 1/3" in report
        assert "未命中: 1/3" in report
        assert "待人工裁决" in report


class TestRender:
    def test_render_includes_stage_and_rounds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        _write_snap(case_dir, "2026-08-15T10:00:00", [_chk("artifacts", "ts.json", "pass")],
                    steps=[{"step": "preprocess", "status": "pass", "duration": 0.3}])
        _write_snap(case_dir, "2026-08-15T11:00:00", [_chk("artifacts", "ts.json", "pass")],
                    steps=[{"step": "preprocess", "status": "pass", "duration": 0.2}])
        snaps = stability.load_recent_snapshots("t", 2)
        report = stability.render_stability("t", snaps)
        assert "每轮结果" in report
        assert "preprocess 2/2" in report


class TestStageTimeStats:
    def test_stage_duration_distribution(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        _write_snap(case_dir, "2026-08-15T10:00:00", [_chk("artifacts", "ts.json", "pass")],
                    steps=[{"step": "preprocess", "status": "pass", "duration": 10}])
        # 手动补 stage_times
        import json as j
        d = case_dir / "2026-08-15T10-00-00" / "result.json"
        data = j.loads(d.read_text(encoding="utf-8"))
        data["stage_times"] = {"预处理": 10.0, "设计决策": 300.0}
        d.write_text(j.dumps(data, ensure_ascii=False), encoding="utf-8")
        _write_snap(case_dir, "2026-08-15T11:00:00", [_chk("artifacts", "ts.json", "pass")])
        d2 = case_dir / "2026-08-15T11-00-00" / "result.json"
        data2 = j.loads(d2.read_text(encoding="utf-8"))
        data2["stage_times"] = {"预处理": 20.0, "设计决策": 400.0}
        d2.write_text(j.dumps(data2, ensure_ascii=False), encoding="utf-8")

        snaps = stability.load_recent_snapshots("t", 2)
        report = stability.render_stability("t", snaps)
        assert "阶段耗时分布" in report
        assert "预处理" in report and "设计决策" in report
        assert "avg" in report and "(2轮)" in report


class TestLoopStats:
    def test_loop_section_rendered(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "RESULTS_DIR", tmp_path)
        case_dir = tmp_path / "t"
        _write_snap(case_dir, "2026-08-15T10:00:00", [_chk("artifacts", "ts.json", "pass")])
        import json as j
        d = case_dir / "2026-08-15T10-00-00" / "result.json"
        data = j.loads(d.read_text(encoding="utf-8"))
        data["stage_loops"] = {"规则编码": 2, "UT执行": 1}
        d.write_text(j.dumps(data, ensure_ascii=False), encoding="utf-8")
        report = stability.render_stability("t", stability.load_recent_snapshots("t", 1))
        assert "执行回路" in report
        assert "规则编码 回路: 1/1 轮" in report
        # UT执行 只出现1次不算回路
        assert "UT执行 回路" not in report
