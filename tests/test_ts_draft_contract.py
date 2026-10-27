# -*- coding: utf-8 -*-
"""ts 草稿契约 v2 schema 测试（2026-10-27 批2：契约方向反转——权威=消费方，逆向侧 vendor）。

契约设计稿的可校验性守卫：schema 可载入/最小合法草稿过验/关键必填段缺失被拦
（_reverse 审核材料段/物理属性恢复槽位/三桶结构）。逆向侧实现前，本测试守的是
契约文件本身不漂（与 baseline_v1 的 vendor 联锁同精神——彼侧 vendor 后由彼侧联锁盯）。
"""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_draft_v2.schema.json"


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
