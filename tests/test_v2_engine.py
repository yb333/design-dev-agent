"""评测 v2 的断言逻辑测试。

用 mock 构造数据验证各层断言逻辑（不依赖具体案例产出）：
- assert_design: business_key / field_targets 覆盖 / load_mode / segmentation
- assert_sql: 字段完整 / JOIN 表 / GROUP BY / SELECT *
- assert_artifacts: 顶层键 / audit_fields / 文件齐全
"""

import json
import sys
from pathlib import Path

import pytest

# v2 模块路径
_V2_DIR = Path(__file__).resolve().parent.parent / "eval-suite" / "v2"
_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import assert_design
import assert_sql


# ============================================================
# assert_design 测试
# ============================================================


def _ts_with(business_key=None, rules=None, segmentation="不分段"):
    """构造最小 ts.json dict。"""
    return {
        "design": {
            "business_key": business_key or ["id"],
            "audit_fields": {"del_flag": {}, "crt_cycle_id": {}, "last_upd_cycle_id": {}, "dw_last_update_date": {}},
            "complexity_analysis": {"segmentation_decision": segmentation},
        },
        "rules": rules or {},
    }


class TestDesignBusinessKey:
    def test_business_key_match(self, tmp_path):
        ts = _ts_with(business_key=["order_id", "dt"])
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"business_key": ["order_id", "dt"]})
        passed = [x for x in r if x.status.value == "pass" and "business_key" in x.detail]
        assert passed, f"应 pass: {[x.detail for x in r]}"

    def test_business_key_mismatch(self, tmp_path):
        ts = _ts_with(business_key=["order_id"])
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"business_key": ["order_id", "dt"]})
        failed = [x for x in r if x.status.value == "fail"]
        assert failed, "business_key 不符应 fail"


class TestDesignFieldTargetsCover:
    def test_cover_complete(self, tmp_path):
        """field_targets 并集 == rs_input target_column 全集 → pass。"""
        rs_input = {"field_mappings": [
            {"target_column": "id"}, {"target_column": "amt"}, {"target_column": "del_flag"}]}
        dec = {"rules": [{"rule_code": "R0001", "field_targets": ["id", "amt", "del_flag"]}]}
        (tmp_path / "ts.json").write_text(json.dumps(_ts_with()), encoding="utf-8")
        (tmp_path / "_internal").mkdir()
        import yaml
        (tmp_path / "_internal" / "design_decisions.yaml").write_text(
            yaml.dump(dec), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {}, rs_input)
        passed = [x for x in r if "完整覆盖" in x.detail]
        assert passed, f"应完整覆盖: {[x.detail for x in r]}"

    def test_cover_missing(self, tmp_path):
        """field_targets 漏了 amt → fail。"""
        rs_input = {"field_mappings": [
            {"target_column": "id"}, {"target_column": "amt"}, {"target_column": "del_flag"}]}
        dec = {"rules": [{"rule_code": "R0001", "field_targets": ["id", "del_flag"]}]}  # 缺 amt
        (tmp_path / "ts.json").write_text(json.dumps(_ts_with()), encoding="utf-8")
        (tmp_path / "_internal").mkdir()
        import yaml
        (tmp_path / "_internal" / "design_decisions.yaml").write_text(
            yaml.dump(dec), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {}, rs_input)
        failed = [x for x in r if "覆盖不全" in x.detail]
        assert failed, f"应报覆盖不全: {[x.detail for x in r]}"


class TestDesignLoadMode:
    def test_valid_load_mode(self, tmp_path):
        ts = _ts_with(rules={"R0001": {"load_mode": "truncate_table"}})
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"load_mode_valid": True})
        passed = [x for x in r if "load_mode 合法" in x.detail]
        assert passed, f"应合法: {[x.detail for x in r]}"

    def test_missing_load_mode(self, tmp_path):
        ts = _ts_with(rules={"R0001": {}})  # 无 load_mode
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"load_mode_valid": True})
        failed = [x for x in r if "无 load_mode" in x.detail]
        assert failed, f"应报缺 load_mode: {[x.detail for x in r]}"

    def test_invalid_load_mode(self, tmp_path):
        ts = _ts_with(rules={"R0001": {"load_mode": "bogus"}})
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"load_mode_valid": True})
        failed = [x for x in r if "非法" in x.detail]
        assert failed, f"应报非法: {[x.detail for x in r]}"


class TestDesignSegmentation:
    def test_no_segment_pass(self, tmp_path):
        ts = _ts_with(segmentation="不分段")
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {})
        passed = [x for x in r if "不分段" in x.detail and x.status.value == "pass"]
        assert passed

    def test_segment_without_reason_fails(self, tmp_path):
        ts = _ts_with(segmentation="分段")
        ts["design"]["complexity_analysis"]["segmentation_reason"] = ""
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {})
        failed = [x for x in r if "segmentation_reason" in x.detail]
        assert failed, f"分段无理由应 fail: {[x.detail for x in r]}"


class TestDesignFieldNotMappedFrom:
    """字段不能映射自某表（数据源缺口陷阱用）。"""

    def _ts_with_field_source(self, field, source_table):
        ts = _ts_with()
        ts["rules"] = {"R0001": {
            "fields": [{
                "target_field": field,
                "source_fields": [{"table": source_table, "field": "x", "alias": "a"}],
            }]
        }}
        return ts

    def test_field_mapped_from_forbidden_fails(self, tmp_path):
        """customer_level 映射自 dim_customer（诱导表）→ fail。"""
        ts = self._ts_with_field_source("customer_level", "dim_customer")
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {
            "field_not_mapped_from": {"field": "customer_level", "not_from_table": "dim_customer"}
        })
        failed = [x for x in r if "错误映射自" in x.detail]
        assert failed, f"映射自禁表应 fail: {[x.detail for x in r]}"

    def test_field_mapped_from_correct_table_passes(self, tmp_path):
        """customer_level 映射自 dwd_customer_rfm（正确表）→ pass。"""
        ts = self._ts_with_field_source("customer_level", "dwd_customer_rfm")
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {
            "field_not_mapped_from": {"field": "customer_level", "not_from_table": "dim_customer"}
        })
        passed = [x for x in r if "未映射自" in x.detail and x.status.value == "pass"]
        assert passed, f"映射自正确表应 pass: {[x.detail for x in r]}"

    def test_field_not_mapped_anywhere_passes(self, tmp_path):
        """customer_level 降级为 assign（缺口标注），不出现在 source_fields → pass。"""
        ts = _ts_with()
        ts["rules"] = {"R0001": {
            "fields": [{
                "target_field": "customer_level",
                "transform_type": "assign",
                "source_fields": [],  # 无源（缺口降级为赋值）
            }]
        }}
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {
            "field_not_mapped_from": {"field": "customer_level", "not_from_table": "dim_customer"}
        })
        passed = [x for x in r if "未映射自" in x.detail and x.status.value == "pass"]
        assert passed, f"缺口降级应 pass: {[x.detail for x in r]}"

    def test_forbidden_table_with_schema_matches_bare(self, tmp_path):
        """not_from_table 带 schema（dim.dim_customer）也能匹配裸表名 dim_customer。"""
        ts = self._ts_with_field_source("customer_level", "dim_customer")
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {
            "field_not_mapped_from": {"field": "customer_level", "not_from_table": "dim.dim_customer"}
        })
        failed = [x for x in r if "错误映射自" in x.detail]
        assert failed, f"带 schema 的禁表应匹配裸表名 fail: {[x.detail for x in r]}"


# ============================================================
# assert_sql 测试
# ============================================================


def _write_select(tmp_path, rule_code, sql):
    etl_dir = tmp_path / "etl"
    etl_dir.mkdir(exist_ok=True)
    (etl_dir / f"{rule_code}.sql").write_text(sql, encoding="utf-8")


class TestCodeFieldsRequired:
    def test_all_fields_present(self, tmp_path):
        sql = """SELECT a.id AS order_id, a.amt AS total, 'N' AS del_flag
                 FROM ods.t a GROUP BY a.id"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"fields_required": ["order_id", "total", "del_flag"]}
        })
        passed = [x for x in r if "字段完整" in x.detail]
        assert passed, f"应字段完整: {[x.detail for x in r]}"

    def test_missing_field(self, tmp_path):
        sql = """SELECT a.id AS order_id FROM ods.t a"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"fields_required": ["order_id", "total"]}
        })
        failed = [x for x in r if "字段缺失" in x.detail]
        assert failed, f"应报字段缺失: {[x.detail for x in r]}"


class TestCodeJoinTables:
    def test_join_covered(self, tmp_path):
        sql = """SELECT a.id FROM ods.fact a JOIN dim.user b ON a.uid=b.id"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"join_tables": ["ods.fact", "dim.user"]}
        })
        passed = [x for x in r if "JOIN 表覆盖" in x.detail]
        assert passed, f"应 JOIN 覆盖: {[x.detail for x in r]}"

    def test_join_missing(self, tmp_path):
        sql = """SELECT a.id FROM ods.fact a"""  # 缺 dim.user
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"join_tables": ["ods.fact", "dim.user"]}
        })
        failed = [x for x in r if "JOIN 表缺失" in x.detail]
        assert failed, f"应报 JOIN 缺失: {[x.detail for x in r]}"


class TestCodeGroupBy:
    def test_groupby_correct(self, tmp_path):
        sql = """SELECT a.uid AS user_id, COUNT(*) AS cnt FROM ods.log a GROUP BY a.uid"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"group_by_granularity": ["uid"]}
        })
        passed = [x for x in r if "GROUP BY 粒度正确" in x.detail]
        assert passed, f"应 GROUP BY 正确: {[x.detail for x in r]}"

    def test_groupby_missing_col(self, tmp_path):
        sql = """SELECT a.uid AS user_id, a.dt AS dt, COUNT(*) AS cnt FROM ods.log a GROUP BY a.uid"""
        # GROUP BY 只有 uid，缺 dt
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"group_by_granularity": ["uid", "dt"]}
        })
        failed = [x for x in r if "GROUP BY 缺列" in x.detail]
        assert failed, f"应报 GROUP BY 缺列: {[x.detail for x in r]}"


class TestCodeSelectStar:
    def test_select_star_fails(self, tmp_path):
        sql = """SELECT * FROM ods.t a"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {"R0001": {"no_select_star": True}})
        failed = [x for x in r if "SELECT *" in x.detail]
        assert failed, f"应报 SELECT *: {[x.detail for x in r]}"

    def test_no_select_star_passes(self, tmp_path):
        sql = """SELECT a.id AS id FROM ods.t a"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {"R0001": {"no_select_star": True}})
        star_fails = [x for x in r if "SELECT *" in x.detail]
        assert not star_fails, "不应报 SELECT *"


class TestCodeGroupByBareSelect:
    """GROUP BY 提取兼容裸 SELECT（原 content.py 只处理 INSERT...SELECT）。"""

    def test_bare_select_groupby(self, tmp_path):
        sql = """SELECT a.user_id AS user_id, SUM(a.amt) AS total
                 FROM ods.log a GROUP BY a.user_id"""
        _write_select(tmp_path, "R0001", sql)
        r = assert_sql.run_code_checks(tmp_path, {
            "R0001": {"group_by_granularity": ["user_id"]}
        })
        # GROUP BY 提取的是源列名 user_id（不是别名），应匹配
        passed = [x for x in r if "GROUP BY 粒度正确" in x.detail]
        assert passed, f"裸 SELECT 的 GROUP BY 应能提取: {[x.detail for x in r]}"


# ============================================================
# 契约断言：rules_expected / load_mode_expected
# ============================================================


class TestRulesExpected:
    def _ts(self, rules):
        return {"design": {"business_key": ["id"], "audit_fields": {},
                           "complexity_analysis": {}}, "rules": rules}

    def test_match_passes(self, tmp_path):
        ts = self._ts({"R0001": {"load_mode": "truncate_table"}})
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {}, rules_expected=["R0001"])
        passed = [x for x in r if "规则集匹配" in x.detail]
        assert passed, f"{[x.detail for x in r]}"

    def test_mismatch_fails(self, tmp_path):
        ts = self._ts({"R0001": {}, "R0002": {}})
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {}, rules_expected=["R0001"])
        failed = [x for x in r if "规则集不符" in x.detail and "缺" not in x.detail.split("（")[0]]
        assert any("多 ['R0002']" in x.detail for x in failed)

    def test_none_skips(self, tmp_path):
        ts = self._ts({})
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {}, rules_expected=None)
        assert not any("规则集" in x.detail for x in r)


class TestLoadModeExpected:
    def _ts(self, code="R0001", mode="merge_into"):
        return {"design": {"business_key": ["id"], "audit_fields": {},
                           "complexity_analysis": {}},
                "rules": {code: {"load_mode": mode}}}

    def test_match_passes(self, tmp_path):
        ts = self._ts()
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"load_mode_expected": {"R0001": "merge_into"}})
        assert any("load_mode 契约匹配" in x.detail for x in r)

    def test_mismatch_fails(self, tmp_path):
        ts = self._ts(mode="truncate_table")
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        r = assert_design.run_design_checks(tmp_path, {"load_mode_expected": {"R0001": "merge_into"}})
        assert any("load_mode 契约不符" in x.detail for x in r)


# ============================================================
# 字段口径签名 + 字段覆盖契约（默认零配置）
# ============================================================


class TestFieldSignatures:
    def test_signature_shape(self):
        sql = "SELECT SUM(a.amt) AS total, a.id AS oid, 'N' AS flag FROM ods.t a GROUP BY a.id"
        sigs = assert_sql._extract_field_signatures(sql)
        assert sigs["total"] == {"refs": ["a.amt"], "aggs": ["SUM"], "consts": []}
        assert sigs["oid"] == {"refs": ["a.id"], "aggs": [], "consts": []}
        assert sigs["flag"] == {"refs": [], "aggs": [], "consts": ["N"]}

    def test_cast_and_coalesce_tolerated(self):
        a = assert_sql._extract_field_signatures("SELECT a.amt AS t FROM ods.t a")
        b = assert_sql._extract_field_signatures("SELECT CAST(COALESCE(a.amt, 0) AS int) AS t FROM ods.t a")
        # COALESCE 引入常量 0 —— refs/口径主体一致，consts 差异如实体现
        assert a["t"]["refs"] == b["t"]["refs"] == ["a.amt"]
        assert "0" in b["t"]["consts"]


class TestFieldCoverageContract:
    """默认契约：SELECT 输出 ⊇ ts 该规则 field_targets（零配置）。"""

    def _ts_with_ft(self, ft):
        return {"design": {"business_key": ["id"], "audit_fields": {},
                           "complexity_analysis": {}},
                "rules": {"R0001": {"load_mode": "truncate_table", "field_targets": ft}}}

    def test_covered_passes(self, tmp_path):
        (tmp_path / "ts.json").write_text(json.dumps(self._ts_with_ft(["order_id", "amt"])), encoding="utf-8")
        _write_select(tmp_path, "R0001", "SELECT a.id AS order_id, a.amt AS amt FROM ods.t a")
        r = assert_sql.run_code_checks(tmp_path, None, ts=self._ts_with_ft(["order_id", "amt"]))
        assert any("字段覆盖契约完整" in x.detail for x in r)

    def test_missing_field_fails(self, tmp_path):
        ts = self._ts_with_ft(["order_id", "amt", "remark"])
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        _write_select(tmp_path, "R0001", "SELECT a.id AS order_id, a.amt AS amt FROM ods.t a")
        r = assert_sql.run_code_checks(tmp_path, None, ts=ts)
        assert any("字段覆盖契约缺字段" in x.detail and "remark" in x.detail for x in r)

    def test_no_field_targets_skips(self, tmp_path):
        ts = self._ts_with_ft([])
        _write_select(tmp_path, "R0001", "SELECT 1 AS x")
        r = assert_sql.run_code_checks(tmp_path, None, ts=ts)
        assert not any("字段覆盖契约" in x.detail for x in r)
