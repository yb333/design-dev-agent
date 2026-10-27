# -*- coding: utf-8 -*-
"""ts 草稿契约 v2 schema 测试（2026-10-27 批2：契约方向反转——权威=消费方，逆向侧 vendor）。

契约交付包三件套的可校验性守卫：①schema 可载入/关键段必填；②**合格样例**
（schemas/ts_draft_v2.example.json）过 schema 验——逆向侧的生成参照物自身合法；
③**形态衔接**：v1 装配器真实产出（build_ts_baseline → normalize_ts 标准形态 →
剥 dq_rules → 附 _reverse）也过 schema——证明 v2 契约与 v1 现产形态兼容，
形态演进（改 assemble_ts_baseline/ts_compat）会在此被拦=契约波次提示。
ts-template.json 为完整结构权威（人读），schema 守契约必填面，消费链校验是终局守。
"""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_draft_v2.schema.json"
EXAMPLE_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_draft_v2.example.json"


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def minimal_draft():
    return {
        "version": "2.0",
        "meta": {
            "target": {"f_table": {"schema": "dws", "table": "dwb_trade_order_d"}},
            "grain": "",
            "business_key": [],           # 无显式主键设计→空（推断不冒充声明）
            "source_tables": [{"schema": "ods", "table": "ods_trade_order_di", "alias": "a"}],
            "schedule": {"schedule_type": "daily", "cron": "0 2 * * ?"},
        },
        "tables": {
            "dwb_trade_order_d": {
                "type": "target",
                "distribution_key": ["order_id"],   # 恢复：table_props/is_distribute_key
                "distribute_type": "HASH",
                "partition": "",
                "fields": [{"target_field": "order_id", "field_type": "VARCHAR(64)",
                            "field_comment": "订单号", "transform_type": "direct",
                            "source_fields": [{"table": "ods_trade_order_di", "field": "order_id",
                                               "alias": "a"}], "design_logic": ""}],
            }
        },
        "rules": {
            "R0001": {
                "target_table": "dws.dwb_trade_order_d",
                "load_mode": "merge_into",
                "write_condition": "T.order_id=T1.order_id",
                "fields": {"direct": ["a.order_id AS order_id"], "processed": [], "assign": []},
            }
        },
        "_reverse": {
            "self_check": {"verdict": "pass_with_noise", "structural_count": 0, "noise_count": 2},
            "warnings": [{"severity": "noise", "title": "登记滞后"}],
            "write_plan": [{"rule_code": "R0001", "kind": "merge_upsert"}],
            "schedule_evidence": [{"task_path": "grp/x/r0001", "cron": "0 2 * * ?"}],
            "evidence": {"business_key": [{"source": "merge_on", "expr": "T.order_id=T1.order_id",
                                           "origin": "R0001"}]},
        },
    }


class TestTsDraftContract:
    def test_minimal_draft_valid(self, validator):
        validator.validate(minimal_draft())

    def test_reverse_section_required(self, validator):
        d = minimal_draft()
        del d["_reverse"]
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(d)

    def test_version_constrained_to_v2(self, validator):
        d = minimal_draft()
        d["version"] = "1.4"
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(d)

    def test_table_physical_props_required(self, validator):
        d = minimal_draft()
        del d["tables"]["dwb_trade_order_d"]["distribution_key"]   # 物理属性恢复槽位必填
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(d)

    def test_rule_buckets_required(self, validator):
        d = minimal_draft()
        del d["rules"]["R0001"]["fields"]["processed"]             # 三桶结构必填
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(d)

    def test_evidence_source_enum(self, validator):
        """旁证来源封闭集：merge_on（强旁证）/dq_pk_check（显式设计可回填）——
        分布键不得作为 business_key 旁证（无唯一性语义，2026-10-27 纠偏定调）。"""
        d = minimal_draft()
        d["_reverse"]["evidence"]["business_key"][0]["source"] = "distribute_by"
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(d)


class TestContractPackage:
    """契约交付包三件套：schema（契约必填面）+ ts-template.json（完整结构权威）+
    合格样例（逆向侧生成参照）。"""

    def test_shipped_example_valid(self, validator):
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        validator.validate(example)
        # 样例必须演示关键契约面：恢复槽位有值+判断位留空+旁证双来源+三桶标准形态
        assert example["tables"]["dwb_cust_asset_d"]["distribution_key"] == ["cust_id"]
        assert example["meta"]["grain"] == "" and example["meta"]["business_key"] == []
        assert {e["source"] for e in example["_reverse"]["evidence"]["business_key"]} == \
            {"merge_on", "dq_pk_check"}
        assert all(isinstance(r["fields"], dict) and "direct" in r["fields"]
                   for r in example["rules"].values())
        assert "dq_rules" not in example          # v2 无 DQ——独立 dq.json 通道

    def test_v1_pipeline_form_compatible(self, validator):
        """形态衔接：v1 装配器真实产出过 v2 契约——证明 v2 契约与 v1 现产形态兼容；
        assemble_ts_baseline/ts_compat 形态演进使此断言失败时=契约波次提示
        （样例文件需随波次再生成）。"""
        import sys
        for d in ("skills/opt-pipe/scripts", "skills/design-dev-shared/scripts"):
            sys.path.insert(0, str(REPO / d))
        from assemble_ts_baseline import build_ts_baseline
        from ts_compat import normalize_ts
        facts = json.loads((REPO / "tests/fixtures/opt/asset_facts_v13_full.json")
                           .read_text(encoding="utf-8"))
        ts, _ = build_ts_baseline(facts)
        draft = normalize_ts(ts)
        draft.pop("dq_rules", None)               # v1 特有 legacy——v2 DQ 走 dq.json
        draft["version"] = "2.0"
        draft["_reverse"] = {
            "self_check": {"verdict": "pass", "structural_count": 0, "noise_count": 0},
            "warnings": [],
            "write_plan": [{"rule_code": c} for c in (facts.get("rules") or [])],
            "schedule_evidence": [], "evidence": {}}
        validator.validate(draft)
