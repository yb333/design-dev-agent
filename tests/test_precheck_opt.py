"""precheck_opt 测试：只检新增子集（命名规范/存在性对账/类型风险决策回写/新来源 JOIN 对账）。
不连库——连库单元用 fake tables dict；main 的无库路径走降级 warn。"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "opt-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from precheck_opt import (
    main, _check_existence_and_types, _check_type_risks, _check_join_risks,
)
from risk_checks import PrecheckResult


def mk_cr(fields):
    return {"change_type": "add_field", "version": "202608", "fields": fields,
            "asset": "dws.dwb_x_d"}


def mk_field(name="channel_name", stype="varchar(64)", ttype="varchar(64)",
             table="dim_channel", alias="c", join="a.shop_id=c.shop_id",
             new_source=True, rule="直取"):
    return {"field": name, "cn": name, "type": ttype,
            "source": {"schema": "dim", "table": table, "alias": alias, "field": name,
                       "source_type": stype, "rule": rule, "expr": "-",
                       "join_condition": join},
            "new_source_table": new_source}


def mk_ts():
    return {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_d"}}},
            "rules": {"R0001": {"source_tables": [
                {"schema": "ods", "table": "ods_order", "alias": "a"}]}}}


TABLES = {("dim", "dim_channel"): {"channel_name": "varchar(64)", "shop_id": "numeric(10)"},
          ("ods", "ods_order"): {"shop_id": "numeric(10)"}}


class TestNaming:
    def test_bad_name_blocked(self, tmp_path):
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(
            mk_cr([mk_field(name="Channel-Name")]), ensure_ascii=False), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        assert rc == 2 or rc == 1  # 无库 warn + 命名 error → error 优先 exit 2
        cr = json.loads(cr_path.read_text(encoding="utf-8"))
        # 命名 error 在（无库路径照样跑离线检查）

    def test_good_name_passes_offline(self, tmp_path):
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(mk_cr([mk_field()])), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        assert rc == 1  # 无库降 warn（存在性+值域各一条），无 error


class TestExistence:
    def test_missing_column_error(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(name="nope", stype="varchar(10)")])
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert any("源字段不存在" in e for e in result.errors)

    def test_declared_type_mismatch_warns_and_backfills(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(stype="varchar(200)")])  # 库里实际 varchar(64)
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert any("以库为准" in w for w in result.warnings)
        assert cr["fields"][0]["source"]["source_type"] == "varchar(64)"

    def test_exact_match_silent(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(stype="varchar(64)")])
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert not result.errors and not result.warnings


class TestTypeRiskDecision:
    def _cr_cross(self):
        # 库类型回填后跨大类：varchar 源 → date 目标
        return mk_cr([mk_field(name="biz_date", stype="varchar(20)", ttype="date")])

    def test_pending_then_decision_written_back(self, tmp_path):
        from risk_checks import _detect_type_risks as detect_type_risks, _generate_type_risk_skeleton as generate_type_risk_skeleton
        cr = self._cr_cross()
        fm = [{"target_column": f["field"], "source_type": f["source"]["source_type"],
               "target_type": f["type"], "transform_rule": "直接复制"} for f in cr["fields"]]
        batch, individual = detect_type_risks({"field_mappings": fm})
        assert individual, "varchar→date 应检出跨大类"
        decision = tmp_path / "type_risk_decision.yaml"
        generate_type_risk_skeleton(decision, batch, individual)
        import yaml
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("跨大类风险字段", []):
            it["处置"] = "转换"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")

        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert not result.errors
        assert "decision" in cr["fields"][0]
        assert "原始输入='直接复制'" in cr["fields"][0]["decision"]
        assert "勿推翻方向" in cr["fields"][0]["decision"]

    def test_return_source_blocks(self, tmp_path):
        from risk_checks import _detect_type_risks as detect_type_risks, _generate_type_risk_skeleton as generate_type_risk_skeleton
        cr = self._cr_cross()
        fm = [{"target_column": f["field"], "source_type": f["source"]["source_type"],
               "target_type": f["type"], "transform_rule": "直接复制"} for f in cr["fields"]]
        batch, individual = detect_type_risks({"field_mappings": fm})
        decision = tmp_path / "type_risk_decision.yaml"
        generate_type_risk_skeleton(decision, batch, individual)
        import yaml
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("跨大类风险字段", []):
            it["处置"], it["原因"] = "返源端", "源端应提供 date"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert any("返源端" in e for e in result.errors), "返源端本轮终止（对齐 new-pipe）"
        assert "decision" not in cr["fields"][0]

    def test_no_pending_stdout_when_clean(self, tmp_path, capsys):
        cr = mk_cr([mk_field(stype="varchar(64)", ttype="varchar(200)")])  # 放宽无风险
        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert "TYPE_RISK_PENDING" not in capsys.readouterr().out


class TestJoinRisk:
    def test_cross_category_detected_and_decision_written(self, tmp_path):
        cr = mk_cr([mk_field(name="channel_name", stype="varchar(64)",
                             join="a.shop_code=c.shop_code")])
        tables = {("dim", "dim_channel"): {"channel_name": "varchar(64)", "shop_code": "varchar(20)"},
                  ("ods", "ods_order"): {"shop_id": "numeric(10)", "shop_code": "numeric(10)"}}
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result)
        assert any("跨大类" in e for e in result.errors)
        dec_path = tmp_path / "join_type_decision.yaml"
        assert dec_path.exists(), "骨架已生成"

        import yaml
        dec = yaml.safe_load(dec_path.read_text(encoding="utf-8"))
        for it in dec.get("关联风险对", []):
            it["处置"] = "转换"
        dec_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result2)
        assert not result2.errors
        assert cr["join_type_decisions"][0]["decision"] == "转换"

    def test_same_type_no_risk(self, tmp_path):
        cr = mk_cr([mk_field(join="a.shop_id=c.shop_id")])  # 两侧 numeric 同族
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), TABLES, tmp_path, tmp_path / "cr.json", result)
        assert not result.errors and not (tmp_path / "join_type_decision.yaml").exists()

    def test_key_change_blocks(self, tmp_path):
        cr = mk_cr([mk_field(name="channel_name", stype="varchar(64)",
                             join="a.shop_code=c.shop_code")])
        tables = {("dim", "dim_channel"): {"channel_name": "varchar(64)", "shop_code": "varchar(20)"},
                  ("ods", "ods_order"): {"shop_id": "numeric(10)", "shop_code": "numeric(10)"}}
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result)
        import yaml
        dec = yaml.safe_load((tmp_path / "join_type_decision.yaml").read_text(encoding="utf-8"))
        for it in dec.get("关联风险对", []):
            it["处置"] = "改关联键"
        (tmp_path / "join_type_decision.yaml").write_text(
            yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result2)
        assert any("改关联键" in e for e in result2.errors)
