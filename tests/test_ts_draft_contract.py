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
import sys
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_draft_v2.schema.json"
EXAMPLE_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_draft_v2.example.json"
FORWARD_SAMPLE_PATH = REPO / "skills" / "opt-pipe" / "schemas" / "ts_sample_forward.json"


def _build_forward_sample() -> dict:
    """真实正向 ts：增量工厂（双 extract+merge，过全量校验的合法 decisions）走
    assemble_ts 真装配——契约包第四件「本体全貌靶」的再生函数（golden 守护用）。"""
    from conftest import make_incremental_rs_input, make_incremental_decisions
    sys.path.insert(0, str(REPO / "skills" / "dws-design" / "scripts"))
    sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))
    from assemble_ts import assemble_ts
    rs = make_incremental_rs_input()
    dd = make_incremental_decisions([
        {"key": "update_time", "table": "ods_test_f", "seq": 1},
        {"key": "dt", "table": "ods_pay_f", "seq": 2}])
    out = assemble_ts(rs, dd)
    return out[0] if isinstance(out, tuple) else out


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def minimal_draft():
    return {
        "version": "2.1",
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
                "query_sql": "SELECT a.order_id AS order_id FROM ods.ods_trade_order_di a",
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

    def test_query_sql_required_v21(self, validator):
        """v2.1 增补：rules[].query_sql 必填（逐字保真 SQL 载体——验收实锤 v2.0 漏项：
        草稿无 SQL 则 baseline etl/coder 底稿/SQL 围栏基准无从诞生）。"""
        d = minimal_draft()
        d["rules"]["R0001"].pop("query_sql")
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

    def test_new_build_form_anchor(self, validator):
        """形态锚=新建链路真装配产出（assemble_ts+全量校验工厂——多轮磨砺的形态），
        不是 v1 逆向装配器（待退役、有前科）。新建 ts 附 _reverse 即过 v2 契约
        ——证明契约目标形态锚定正确；assemble_ts 形态演进使此断言失败时=契约
        波次提示（样例文件随波次再核对）。"""
        ts = _build_forward_sample()
        draft = dict(ts)
        draft["version"] = "2.1"
        draft["_reverse"] = {
            "self_check": {"verdict": "pass", "structural_count": 0, "noise_count": 0},
            "warnings": [], "write_plan": [], "schedule_evidence": [], "evidence": {}}
        # 正向 ts 不带 query_sql（SQL 后产于 etl/）——草稿契约必填，注入占位证明兼容
        for r in draft["rules"].values():
            r.setdefault("query_sql", "-- placeholder（正向链路 SQL 在 etl/ 文件）")
        validator.validate(draft)
        assert "dq_rules" not in draft            # 新建 ts 无 DQ——v2 草稿同口径

    def test_forward_sample_golden(self, validator):
        """契约包第四件「本体全貌靶」（逆向侧点名要的真实正向 ts）golden 守护：
        文件=真装配原样产出（不掺说明键），再生比对剥 volatile 的 generated_at。
        assemble_ts 形态演进使本断言失败=契约波次提示（样本需随波次再生成）。"""
        shipped = json.loads(FORWARD_SAMPLE_PATH.read_text(encoding="utf-8"))
        regen = _build_forward_sample()
        shipped.pop("generated_at", None), regen.pop("generated_at", None)
        assert shipped == regen
        # 全貌性：多规则增量链（extract×2+merge）+三桶+判断位有值（正向真产出特征）
        assert list(shipped["rules"].keys()) == ["R0001", "R0002", "R0003"]
        assert all(isinstance(r.get("fields"), dict) for r in shipped["rules"].values())
        assert shipped["meta"]["grain"]
        assert shipped["tables"]["dwb_test_f"]["business_key"]      # 表级化（2026-09-15）
        assert shipped["rules"]["R0003"]["load_mode"] == "merge_into"
