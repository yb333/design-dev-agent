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


@pytest.fixture(scope="module")
def schema():
    return load_schema()


@pytest.fixture(scope="module")
def demo():
    return json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))


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
