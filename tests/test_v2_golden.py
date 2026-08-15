"""golden 指纹比对测试：提取/比对/命中检查（多解兼容、无 golden 跳过、越界 FAIL）。"""

import json
import shutil
import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import golden


def _make_deliver(tmp_path: Path, business_key=None) -> Path:
    """造一份最小产出（ts.json + decisions + etl SELECT）。"""
    deliver = tmp_path / "ddlc_design_dev"
    (deliver / "_internal").mkdir(parents=True)
    (deliver / "etl").mkdir()
    ts = {
        "design": {"business_key": business_key or ["order_id"], "audit_fields": {}},
        "rules": {"R0001": {"load_mode": "truncate_table"}},
    }
    (deliver / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
    (deliver / "etl" / "R0001.sql").write_text(
        "SELECT a.id AS order_id, 'N' AS del_flag FROM ods.t a GROUP BY a.id",
        encoding="utf-8",
    )
    (deliver / "_internal" / "design_decisions.yaml").write_text(
        "rules:\n- rule_code: R0001\n  field_targets: [order_id, amt]\n", encoding="utf-8"
    )
    return deliver


class TestFingerprint:
    def test_extract_core_facts(self, tmp_path):
        deliver = _make_deliver(tmp_path)
        fp = golden.fingerprint(deliver)
        assert fp["business_key"] == ["order_id"]
        assert fp["rules"] == ["R0001"]
        assert fp["load_modes"] == {"R0001": "truncate_table"}
        assert fp["field_targets"] == ["amt", "order_id"]
        sel = fp["selects"]["R0001"]
        assert "order_id" in sel["fields"] and "del_flag" in sel["fields"]
        assert "id" in sel["group_by"]

    def test_empty_when_no_ts(self, tmp_path):
        assert golden.fingerprint(tmp_path)["rules"] == []


class TestCompare:
    def test_identical_hits(self, tmp_path):
        a = golden.fingerprint(_make_deliver(tmp_path / "a"))
        b = golden.fingerprint(_make_deliver(tmp_path / "b"))
        hit, diffs = golden.compare(a, b)
        assert hit and diffs == []

    def test_business_key_diff_misses(self, tmp_path):
        a = golden.fingerprint(_make_deliver(tmp_path / "a", business_key=["order_id"]))
        b = golden.fingerprint(_make_deliver(tmp_path / "b", business_key=["order_id", "cust_id"]))
        hit, diffs = golden.compare(a, b)
        assert not hit and "business_key" in diffs

    def test_select_fields_diff(self, tmp_path):
        a = golden.fingerprint(_make_deliver(tmp_path / "a"))
        d = _make_deliver(tmp_path / "b")
        (d / "etl" / "R0001.sql").write_text(
            "SELECT a.id AS order_id FROM ods.t a", encoding="utf-8")
        b = golden.fingerprint(d)
        hit, diffs = golden.compare(a, b)
        assert not hit and "R0001:输出字段" in diffs


class TestGoldenCheck:
    def test_skip_when_no_golden(self, tmp_path):
        deliver = _make_deliver(tmp_path / "deliver")
        case = tmp_path / "case"
        case.mkdir()
        results = golden.golden_check(deliver, case)
        assert results[0].status.value == "skip"
        assert "无 golden" in results[0].detail

    def test_pass_on_hit(self, tmp_path):
        deliver = _make_deliver(tmp_path / "deliver")
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(deliver, case / "golden" / "方案A")
        results = golden.golden_check(deliver, case)
        assert results[0].status.value == "pass"
        assert "命中 golden: 方案A" in results[0].detail

    def test_fail_on_miss_with_nearest_diff(self, tmp_path):
        deliver = _make_deliver(tmp_path / "deliver", business_key=["order_id"])
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(
            _make_deliver(tmp_path / "g", business_key=["order_id", "cust_id"]),
            case / "golden" / "方案A",
        )
        results = golden.golden_check(deliver, case)
        assert results[0].status.value == "fail"
        assert "未命中" in results[0].detail and "business_key" in results[0].detail

    def test_multi_golden_any_hit(self, tmp_path):
        """多解兼容：golden 集合里有 A/B 两个方案，产出命中 B 即过。"""
        deliver = _make_deliver(tmp_path / "deliver", business_key=["order_id", "cust_id"])
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(_make_deliver(tmp_path / "ga", business_key=["order_id"]),
                        case / "golden" / "方案A")
        shutil.copytree(_make_deliver(tmp_path / "gb", business_key=["order_id", "cust_id"]),
                        case / "golden" / "方案B")
        results = golden.golden_check(deliver, case)
        assert results[0].status.value == "pass"
        assert "方案B" in results[0].detail
