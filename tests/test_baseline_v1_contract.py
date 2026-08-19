"""baseline_v1 契约测试：vendored schema + fixture 消费（docs/specs/opt/09-契约 §四）。

双端契约测试的我方半边：vendor fixture 必须通过 vendored schema 与消费端校验器。
（analyzer 侧 CI 断言 export 过 schema——同 schema 不同仓，不跨仓 import。）
"""
import json
import copy
from pathlib import Path

import pytest

from baseline_contract import load_schema, validate_baseline_v1, SUPPORTED_VERSIONS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"
DEMO_FIXTURE = FIXTURES / "baseline_v1_demo_full.json"
# v1.1 增量合并案例（analyzer 仓 docs/baseline_v1-案例 产物的 vendor 拷贝）
MERGE_FIXTURE = FIXTURES / "baseline_v1_case_merge_upsert.json"


@pytest.fixture(scope="module")
def schema():
    return load_schema()


@pytest.fixture(scope="module")
def demo():
    return json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def merge_case():
    return json.loads(MERGE_FIXTURE.read_text(encoding="utf-8"))


class TestSchemaSelfCheck:
    def test_vendored_schema_is_valid_draft202012(self, schema):
        # vendor 拷贝本身必须是合法 schema（防手抖改坏）
        Draft202012Validator = __import__("jsonschema").Draft202012Validator
        Draft202012Validator.check_schema(schema)

    def test_supported_versions_nonempty(self):
        assert SUPPORTED_VERSIONS, "支持的契约版本清单不能为空"


class TestPositive:
    def test_demo_fixture_passes(self, schema, demo):
        """vendor fixture（analyzer demo 资产的契约投影）必须全绿通过。"""
        errors = validate_baseline_v1(demo, schema)
        assert errors == [], "fixture 应通过契约校验，违规: " + "; ".join(errors)

    def test_fixture_is_verbatim_sql(self, demo):
        """query_sql 逐字保真抽查：与 fixture 内 lineage raw_expr 对得上（无美化痕迹）。"""
        r1 = next(r for r in demo["rules"] if r["rule_code"] == "R0001")
        assert "WHERE a.del='N'" in r1["query_sql"], "SQL 原文应保留原样（含紧凑写法）"


class TestV11MergeCase:
    """v1.1 增量合并案例（analyzer 仓产出物 vendor 拷贝）——write_plan 与向后兼容。"""

    def test_merge_case_passes(self, schema, merge_case):
        errors = validate_baseline_v1(merge_case, schema)
        assert errors == [], "v1.1 案例应通过校验，违规: " + "; ".join(errors)

    def test_dm6_rule_has_write_plan_and_merge_on(self, merge_case):
        r2 = next(r for r in merge_case["rules"] if r["delete_mode"] == "6")
        assert r2["merge_on"], "dm=6 必供 merge_on"
        wp = r2["write_plan"]
        assert wp["kind"] == "merge_upsert"
        assert wp["condition_role"] == "on_predicate"
        assert wp["condition_columns"], "谓词列引用非空（围栏消费点）"
        assert wp["condition_source"] == "delete_condition"

    def test_v10_shape_passes_v11_schema(self, schema, merge_case):
        """向后兼容：v1.0 形态产物（无 write_plan、version=1.0）必须仍通过 v1.1 vendored schema。"""
        v10 = copy.deepcopy(merge_case)
        v10["version"] = "1.0"
        for r in v10["rules"]:
            r.pop("write_plan", None)
        errors = validate_baseline_v1(v10, schema)
        assert errors == []

    def test_write_plan_missing_is_v10_gap_not_violation(self, merge_case):
        """v1.0 形态（缺 write_plan）契约合法；缺失处理归消费端缺口机制（见 assemble_ts_baseline 测试）。"""
        v10 = copy.deepcopy(merge_case)
        v10["version"] = "1.0"
        for r in v10["rules"]:
            r.pop("write_plan", None)
        assert validate_baseline_v1(v10) == []

    def test_all_rules_have_write_plan_in_v11(self, merge_case):
        """v1.1 产物全规则带 write_plan（含 dm=1 的无条件形态）。"""
        for r in merge_case["rules"]:
            assert "write_plan" in r, f"{r['rule_code']} 缺 write_plan"
        r1 = next(r for r in merge_case["rules"] if r["delete_mode"] == "1")
        assert r1["write_plan"]["kind"] == "full_truncate"
        assert r1["write_plan"]["condition_expr"] is None  # 显式 null 非省略


class TestNegative:
    def test_missing_version(self, schema, demo):
        bad = copy.deepcopy(demo)
        del bad["version"]
        errors = validate_baseline_v1(bad, schema)
        assert any("version" in e for e in errors)

    def test_unsupported_version(self, schema, demo):
        bad = copy.deepcopy(demo)
        bad["version"] = "9.9"
        errors = validate_baseline_v1(bad, schema)
        assert any("不支持的版本" in e for e in errors)

    def test_missing_query_sql(self, schema, demo):
        bad = copy.deepcopy(demo)
        del bad["rules"][0]["query_sql"]
        errors = validate_baseline_v1(bad, schema)
        assert any("query_sql" in e for e in errors)

    def test_dm6_requires_merge_on(self, schema, demo):
        bad = copy.deepcopy(demo)
        bad["rules"][0]["delete_mode"] = "6"
        errors = validate_baseline_v1(bad, schema)
        assert any("merge_on" in e for e in errors), "dm=6 缺 merge_on 必须被语义检查拦下"

    def test_dm6_with_merge_on_passes_semantic_check(self, schema, demo):
        bad = copy.deepcopy(demo)
        bad["rules"][0]["delete_mode"] = "6"
        bad["rules"][0]["merge_on"] = "T.order_id = T1.order_id"
        errors = validate_baseline_v1(bad, schema)
        assert not any("merge_on" in e for e in errors)

    def test_missing_top_level_required(self, schema, demo):
        bad = copy.deepcopy(demo)
        del bad["provenance"]
        errors = validate_baseline_v1(bad, schema)
        assert any("provenance" in e for e in errors)

    def test_schedule_null_is_explicit_gap(self, schema, demo):
        """schedule 为显式 null 必须合法（缺口显式化，不是违规）。"""
        bad = copy.deepcopy(demo)
        bad["schedule"] = None
        errors = validate_baseline_v1(bad, schema)
        assert errors == []
