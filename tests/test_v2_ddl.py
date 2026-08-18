"""DDL 自洽断言 + golden DDL 指纹 + 差异证据测试。"""

import json
import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import assert_artifacts
import golden


def _make_deliver(tmp_path: Path, tables: dict, f_table="dwb_x_f", i_view="dwb_x_i") -> Path:
    """造带 tables 定义的 ts.json + 对应 DDL/视图/回退文件。"""
    d = tmp_path / "ddlc_design_dev"
    (d / "ddl").mkdir(parents=True)
    (d / "ddl_rollback").mkdir(parents=True)
    ts = {
        "meta": {"target": {
            "f_table": {"table": f_table},
            "i_view": {"table": i_view},
        }},
        "design": {"business_key": ["id"],
                   "audit_fields": {"del_flag": {}, "crt_cycle_id": {},
                                    "last_upd_cycle_id": {}, "dw_last_update_date": {}}},
        "tables": tables,
    }
    (d / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
    return d


def _write_table_ddl(d: Path, table: str, cols: list[tuple[str, str]], dist: str = ""):
    lines = [f"CREATE TABLE {table} ("]
    lines += [f"  {c} {t}," for c, t in cols]
    ddl = "\n".join(lines).rstrip(",") + "\n)"
    if dist:
        ddl += f"\n{dist};"
    (d / "ddl" / f"create_table_{table}.sql").write_text(ddl + ";", encoding="utf-8")


GOOD_COLS = [("id", "varchar(50)"), ("amt", "decimal(18,2)"), ("del_flag", "char(1)"),
             ("crt_cycle_id", "varchar(10)"), ("last_upd_cycle_id", "varchar(10)"),
             ("dw_last_update_date", "date")]


class TestDdlConsistency:
    def _ts_tables(self):
        return {"dwb_x_f": {
            "type": "target",
            "distribution_key": ["id"],
            "fields": [{"target_field": "id", "field_type": "varchar(50)"},
                        {"target_field": "amt", "field_type": "decimal(18,2)"}],
        }}

    def test_consistent_passes(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        _write_table_ddl(d, "dwb_x_f", GOOD_COLS, "DISTRIBUTE BY HASH(id)")
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text(
            "DROP TABLE IF EXISTS dwb_x_f;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        fails = [x for x in r if x.status.value == "fail" and "DDL" in x.detail]
        assert not fails, [x.detail for x in r]

    def test_missing_column_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        cols = [c for c in GOOD_COLS if c[0] != "amt"]  # 缺 amt
        _write_table_ddl(d, "dwb_x_f", cols, "DISTRIBUTE BY HASH(id)")
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text("DROP TABLE x;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("DDL缺列" in x.detail and "amt" in x.detail for x in r)

    def test_type_mismatch_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        cols = [("id", "varchar(50)"), ("amt", "int")] + GOOD_COLS[2:]  # amt 类型错
        _write_table_ddl(d, "dwb_x_f", cols, "DISTRIBUTE BY HASH(id)")
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text("DROP TABLE x;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("DDL类型" in x.detail and "amt" in x.detail for x in r)

    def test_dist_key_missing_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        _write_table_ddl(d, "dwb_x_f", GOOD_COLS)  # 没有 DISTRIBUTE BY
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text("DROP TABLE x;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("DISTRIBUTE BY" in x.detail for x in r)

    def test_extra_non_audit_column_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        cols = GOOD_COLS + [("remark2", "varchar(10)")]  # 非审计多余列
        _write_table_ddl(d, "dwb_x_f", cols, "DISTRIBUTE BY HASH(id)")
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text("DROP TABLE x;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("DDL多出非审计列" in x.detail and "remark2" in x.detail for x in r)

    def test_view_missing_columns_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        _write_table_ddl(d, "dwb_x_f", GOOD_COLS, "DISTRIBUTE BY HASH(id)")
        (d / "ddl" / "create_view_dwb_x_i.sql").write_text(
            "CREATE VIEW dwb_x_i AS SELECT id, amt FROM dwb_x_f;", encoding="utf-8")  # 缺审计列
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text("DROP TABLE x;", encoding="utf-8")
        (d / "ddl_rollback" / "rollback_create_view_dwb_x_i.sql").write_text("DROP VIEW x;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("I视图列缺" in x.detail for x in r)

    def test_rollback_without_drop_fails(self, tmp_path):
        d = _make_deliver(tmp_path, self._ts_tables())
        _write_table_ddl(d, "dwb_x_f", GOOD_COLS, "DISTRIBUTE BY HASH(id)")
        (d / "ddl_rollback" / "rollback_create_table_dwb_x_f.sql").write_text(
            "-- 空回退\nSELECT 1;", encoding="utf-8")
        r = assert_artifacts.run_artifact_checks(d)
        assert any("回退SQL缺DROP" in x.detail for x in r)


class TestGoldenDdlDimension:
    def test_parse_ddl_columns(self, tmp_path):
        f = tmp_path / "t.sql"
        f.write_text("CREATE TABLE t (\n  id varchar(50),\n  amt decimal(18,2)\n)\nDISTRIBUTE BY HASH(id);",
                     encoding="utf-8")
        cols = golden.parse_ddl_columns(f)
        assert cols == {"id": "varchar(50)", "amt": "decimal(18,2)"}

    def test_ddl_diff_detected_in_compare(self, tmp_path):
        def mk(name, amt_type):
            d = tmp_path / name
            (d / "ddl").mkdir(parents=True)
            (d / "ts.json").write_text(json.dumps({
                "design": {"business_key": ["id"]},
                "rules": {"R0001": {"load_mode": "truncate_table"}},
                "tables": {"t1": {"type": "target", "distribution_key": ["id"], "fields": []}},
            }), encoding="utf-8")
            (d / "etl").mkdir()
            (d / "etl" / "R0001.sql").write_text("SELECT 1 AS x", encoding="utf-8")
            (d / "ddl" / "create_table_t1.sql").write_text(
                f"CREATE TABLE t1 (\n  id varchar(50),\n  amt {amt_type}\n);", encoding="utf-8")
            return golden.fingerprint(d)

        a, b = mk("a", "decimal(18,2)"), mk("b", "int")
        hit, diffs = golden.compare(a, b)
        assert not hit and any("DDL" in x for x in diffs)

    def test_miss_evidence_golden_vs_actual(self, tmp_path):
        """miss 详情必须并排给出 golden= vs 实际= 证据。"""
        deliver = _make_deliver(tmp_path / "deliver", {"t1": {
            "type": "target", "distribution_key": ["id"], "fields": []}})
        case = tmp_path / "case"
        case.mkdir()
        g = _make_deliver(tmp_path / "g", {"t1": {
            "type": "target", "distribution_key": ["id"], "fields": []}})
        # golden 的 business_key 不同
        import shutil
        shutil.copytree(g, case / "golden" / "方案A")
        gts = json.loads((case / "golden" / "方案A" / "ts.json").read_text(encoding="utf-8"))
        gts["design"]["business_key"] = ["order_id"]
        (case / "golden" / "方案A" / "ts.json").write_text(json.dumps(gts), encoding="utf-8")

        results = golden.golden_check(deliver, case)
        assert results[0].status.value == "fail"
        assert "golden=" in results[0].detail and "实际=" in results[0].detail
        assert "business_key" in results[0].detail
