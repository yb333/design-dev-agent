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
        "rules": {"R0001": {"load_mode": "truncate_table", "target_table": "dwb.x_f",
                            "source_tables": [{"schema": "ods", "table": "ods_a", "alias": "a"}]}},
        "tables": {"tmp1": {"type": "intermediate", "distribution_key": ["order_id"],
                            "build_mode": ""}},
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


class TestFingerprintStructureFacts:
    """表结构事实（类型/分布键/build_mode）+ 规则数据流（源/目标表）进指纹。"""

    def _deliver_with_facts(self, tmp_path, name, dist_key, target):
        import json as j
        d = tmp_path / name
        (d / "_internal").mkdir(parents=True)
        (d / "etl").mkdir()
        (d / "ts.json").write_text(j.dumps({
            "design": {"business_key": ["order_id"]},
            "rules": {"R0001": {"load_mode": "truncate_table", "target_table": target,
                                "source_tables": [{"table": "ods_a"}]}},
            "tables": {"tmp1": {"type": "intermediate", "distribution_key": dist_key}},
        }), encoding="utf-8")
        (d / "etl" / "R0001.sql").write_text("SELECT 1 AS x", encoding="utf-8")
        return d

    def test_distribution_key_diff_detected(self, tmp_path):
        a = golden.fingerprint(self._deliver_with_facts(tmp_path, "a", ["order_id"], "dwb.x_f"))
        b = golden.fingerprint(self._deliver_with_facts(tmp_path, "b", ["cust_id"], "dwb.x_f"))
        hit, diffs = golden.compare(a, b)
        assert not hit and any("表结构" in d for d in diffs)

    def test_rule_flow_diff_detected(self, tmp_path):
        a = golden.fingerprint(self._deliver_with_facts(tmp_path, "a", ["order_id"], "dwb.x_f"))
        b = golden.fingerprint(self._deliver_with_facts(tmp_path, "b", ["order_id"], "dwb.y_f"))
        hit, diffs = golden.compare(a, b)
        assert not hit and any("规则数据流" in d for d in diffs)

    def test_fingerprint_contains_facts(self, tmp_path):
        fp = golden.fingerprint(self._deliver_with_facts(tmp_path, "a", ["order_id"], "dwb.x_f"))
        assert fp["tables"]["tmp1"]["distribution_key"] == ["order_id"]
        assert fp["rule_flow"]["R0001"]["target"] == "dwb.x_f"
        assert fp["rule_flow"]["R0001"]["sources"] == ["ods_a"]


class TestFieldSignatureDimension:
    """L3 映射忠实度进 golden：字段级口径签名（refs/aggs/consts）。"""

    def _deliver_with_sql(self, tmp_path, name, sql):
        import json as j
        d = tmp_path / name
        (d / "_internal").mkdir(parents=True)
        (d / "etl").mkdir()
        (d / "ts.json").write_text(j.dumps({
            "design": {"business_key": ["order_id"]},
            "rules": {"R0001": {"load_mode": "truncate_table"}},
        }), encoding="utf-8")
        (d / "etl" / "R0001.sql").write_text(sql, encoding="utf-8")
        return d

    def test_cast_wrap_same_signature(self, tmp_path):
        """CAST 包裹（类型适配）不改口径签名——合法变体不误杀。"""
        a = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "a", "SELECT a.amt AS total_amt FROM ods.t a"))
        b = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "b", "SELECT CAST(a.amt AS decimal(18,2)) AS total_amt FROM ods.t a"))
        hit, diffs = golden.compare(a, b)
        assert hit, f"CAST 包裹应视为同一口径: {diffs}"

    def test_sum_vs_bare_column_detected(self, tmp_path):
        """SUM(amt) vs 裸 amt——聚合口径不同必须 diff。"""
        a = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "a", "SELECT SUM(a.amt) AS total_amt FROM ods.t a"))
        b = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "b", "SELECT a.amt AS total_amt FROM ods.t a"))
        hit, diffs = golden.compare(a, b)
        assert not hit and any("口径逻辑" in d and "total_amt" in d for d in diffs)

    def test_wrong_source_column_detected(self, tmp_path):
        """同函数但引用错列（a.amt vs b.amt）必须 diff。"""
        a = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "a", "SELECT SUM(a.amt) AS total FROM ods.t a"))
        b = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "b", "SELECT SUM(b.amt) AS total FROM ods.t b"))
        hit, diffs = golden.compare(a, b)
        assert not hit and any("口径逻辑" in d for d in diffs)

    def test_const_value_change_detected(self, tmp_path):
        """赋值/CASE 常量变了（'N' vs 0）必须 diff。"""
        a = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "a", "SELECT 'N' AS del_flag FROM ods.t"))
        b = golden.fingerprint(self._deliver_with_sql(
            tmp_path, "b", "SELECT 0 AS del_flag FROM ods.t"))
        hit, diffs = golden.compare(a, b)
        assert not hit and any("口径常量" in d and "del_flag" in d for d in diffs)


class TestDdlTypeGranularity:
    """DDL 三层：列（致命）/基类型（致命）/精度（非致命只扣分）。"""

    def _fp(self, tmp_path, name, amt_type):
        import json as j
        d = tmp_path / name
        (d / "ddl").mkdir(parents=True)
        (d / "etl").mkdir()
        (d / "ts.json").write_text(j.dumps({
            "design": {"business_key": ["id"]},
            "rules": {"R0001": {"load_mode": "truncate_table"}},
            "tables": {"t1": {"type": "target", "distribution_key": ["id"], "fields": []}},
        }), encoding="utf-8")
        (d / "etl" / "R0001.sql").write_text("SELECT 1 AS x", encoding="utf-8")
        (d / "ddl" / "create_table_t1.sql").write_text(
            f"CREATE TABLE t1 (\n  id varchar(50),\n  amt {amt_type}\n);", encoding="utf-8")
        return golden.fingerprint(d)

    def test_precision_diff_nonfatal_label(self, tmp_path):
        a = self._fp(tmp_path, "a", "decimal(18,2)")
        b = self._fp(tmp_path, "b", "decimal(20,6)")
        hit, diffs = golden.compare(a, b)
        assert not hit
        assert any("DDL(类型精度)" in d for d in diffs)
        assert not any("DDL(基类型)" in d for d in diffs)

    def test_base_type_diff_fatal_label(self, tmp_path):
        a = self._fp(tmp_path, "a", "decimal(18,2)")
        b = self._fp(tmp_path, "b", "int")
        hit, diffs = golden.compare(a, b)
        assert not hit and any("DDL(基类型)" in d for d in diffs)

    def test_same_base_hit(self, tmp_path):
        """基类型相同（精度不同）不拦及格——但仍是差异（扣分项）。"""
        a = self._fp(tmp_path, "a", "varchar(50)")
        b = self._fp(tmp_path, "b", "varchar(100)")
        hit, diffs = golden.compare(a, b)
        assert not hit and len([d for d in diffs if "DDL" in d]) == 1  # 只有精度差异
