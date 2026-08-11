"""assemble_ts.py 的 build_rule 测试。

重点覆盖 source_tables 的"留空兜底"行为：
designer 在 design_decisions 里把 source_aliases 留空（或省略）时，
脚本应默认用 rs_input 的所有 source_tables 补全（见 design_decisions 模板注释）。

回归背景：build_rule 原先只在 source_aliases 非空时填 source_tables，
留空时产出 []，导致 check_sql 报"SELECT 引用了不在 ts.json source_tables 里的表"。
"""

import json
import pytest

from assemble_ts import build_rule, run_all_validations, validate_quartz_cron, ValidationResult


def _rs_sources():
    """构造 rs_input 风格的 source_tables（按别名可寻）。"""
    return [
        {"source_alias": "dpf", "source_schema": "sdinv", "source_table": "dwd_purchase_f"},
        {"source_alias": "dsf", "source_schema": "dim", "source_table": "dim_supplier_f"},
        {"source_alias": "dif", "source_schema": "sdinv", "source_table": "dwd_inventory_f"},
    ]


def test_source_aliases_empty_falls_back_to_all_rs_sources():
    """source_aliases 留空 -> 用 rs_input 全部 source_tables。"""
    rule, _ = build_rule({"rule_code": "R0001", "source_aliases": []}, {}, _rs_sources())
    tables = [s["table"] for s in rule["source_tables"]]
    assert tables == ["dwd_purchase_f", "dim_supplier_f", "dwd_inventory_f"]
    # schema/alias 也应补全
    assert rule["source_tables"][0] == {
        "schema": "sdinv", "table": "dwd_purchase_f", "alias": "dpf"}


def test_source_aliases_missing_falls_back_to_all_rs_sources():
    """source_aliases 键省略（None）-> 同样兜底。"""
    rule, _ = build_rule({"rule_code": "R0001"}, {}, _rs_sources())
    assert len(rule["source_tables"]) == 3


def test_source_aliases_explicit_only_lists_those():
    """designer 显式列了别名 -> 只产出这些（不兜底）。"""
    rule, _ = build_rule(
        {"rule_code": "R0001", "source_aliases": ["dpf"]}, {}, _rs_sources())
    assert len(rule["source_tables"]) == 1
    assert rule["source_tables"][0]["table"] == "dwd_purchase_f"


def test_source_aliases_empty_and_no_rs_sources_yields_empty():
    """两边都空 -> source_tables 为 []（不报错）。"""
    rule, _ = build_rule({"rule_code": "R0001", "source_aliases": []}, {}, [])
    assert rule["source_tables"] == []


# ============================================================
# validate_decisions 测试：多步骤模型下的字段分配校验
# ============================================================

from assemble_ts import validate_decisions


def _field_map(*names):
    """构造 field_map：{字段名: field_mapping记录}。"""
    return {n: {"target_column": n} for n in names}


class TestValidateDecisions:
    """多步骤模型：同字段可跨表，同表内不能重复。"""

    def test_simple_single_rule_passes(self):
        """简单单规则：覆盖所有字段 → 通过。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id", "name"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        assert errors == []

    def test_same_field_across_intermediate_and_target_passes(self):
        """★ 同字段在中间表+目标表各一份 → 不报错（多步骤核心场景）。

        user_id 在 tmp1 和目标表都有——这是正常的字段透传，不是重复分配。
        """
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "tmp1",
             "target_role": "intermediate", "field_targets": ["user_id", "total_amt"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["user_id", "total_amt", "name"]},
        ]}
        errors = validate_decisions(decisions, _field_map("user_id", "total_amt", "name"))
        assert errors == [], f"同字段跨表不应报错: {errors}"

    def test_same_field_same_table_two_rules_reports(self):
        """同一张表被两个规则声明同一字段 → 报错（真重复）。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]},
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        dup_errors = [e for e in errors if "重复" in e]
        assert dup_errors, f"同表重复应报错: {errors}"

    def test_target_not_covering_all_fields_reports(self):
        """目标表规则没覆盖 rs_input 所有字段 → 报缺失。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name", "amount"))
        missing_errors = [e for e in errors if "没有分配" in e]
        assert missing_errors, f"应报字段缺失: {errors}"
        assert "name" in missing_errors[0] and "amount" in missing_errors[0]

    def test_intermediate_not_covering_all_is_ok(self):
        """中间表字段不要求覆盖 rs_input（中间表可能有 designer 自建字段）。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "tmp1",
             "target_role": "intermediate", "field_targets": ["user_id"]},
            {"rule_code": "R0002", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["user_id", "name", "amount"]},
        ]}
        errors = validate_decisions(decisions, _field_map("user_id", "name", "amount"))
        assert errors == [], f"中间表不要求全覆盖: {errors}"

    def test_field_not_in_rs_input_reports(self):
        """field_targets 里有 rs_input 找不到的字段 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id", "nonexistent"]}
        ]}
        errors = validate_decisions(decisions, _field_map("id", "name"))
        not_found = [e for e in errors if "找不到" in e]
        assert not_found, f"应报找不到字段: {errors}"

    def test_empty_field_targets_reports(self):
        """规则 field_targets 为空 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": []}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert any("为空" in e for e in errors)

    def test_write_condition_required_for_merge(self):
        """merge_into 的 write_condition 为空 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"],
             "load_mode": "merge_into", "write_condition": ""}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        wc_errors = [e for e in errors if "write_condition" in e]
        assert wc_errors, f"merge 无 write_condition 应报错: {errors}"

    def test_write_condition_required_for_partition(self):
        """truncate_partition 的 write_condition 为空 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"],
             "load_mode": "truncate_partition", "write_condition": ""}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert any("write_condition" in e for e in errors)

    def test_write_condition_chinese_reports(self):
        """write_condition 含中文 → 报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"],
             "load_mode": "merge_into", "write_condition": "T.id=匹配ID"}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert any("中文" in e for e in errors)

    def test_write_condition_valid_passes(self):
        """merge 的 write_condition 合法（英文SQL片段）→ 不报 write_condition 错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"],
             "load_mode": "merge_into", "write_condition": "T.id=T1.id"}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert not any("write_condition" in e for e in errors)

    def test_truncate_table_no_write_condition_ok(self):
        """truncate_table 不需要 write_condition → 不报错。"""
        decisions = {"rules": [
            {"rule_code": "R0001", "target_table": "dwb_test_f",
             "target_role": "target", "field_targets": ["id"],
             "load_mode": "truncate_table", "write_condition": ""}
        ]}
        errors = validate_decisions(decisions, _field_map("id"))
        assert not any("write_condition" in e for e in errors)


# ============================================================
# build_rule 多步骤字段搬运：step_type / target_role / produces_for / reads
# ============================================================

class TestBuildRuleStepFields:
    """build_rule 把 step_type/target_role/produces_for/reads 搬进 ts.json 的 rule。

    回归背景：design-decisions-template 里这几个字段 designer 已能填，但 build_rule
    不搬，导致 ts.json 的 rule 丢了步骤类型/依赖声明——多步骤数据流断层。
    """

    def test_defaults_when_absent(self):
        """旧 design_decisions（无新字段）-> 用默认值不报错。"""
        rule, _ = build_rule(
            {"rule_code": "R0001", "source_aliases": []}, {}, _rs_sources())
        assert rule["step_type"] == "full"
        assert rule["target_role"] == "target"
        assert rule["produces_for"] == []
        assert rule["reads"] == []

    def test_explicit_values_carried(self):
        """designer 显式填了 -> 正确搬入。"""
        rule, _ = build_rule({
            "rule_code": "R0001",
            "source_aliases": [],
            "step_type": "aggregate",
            "target_role": "intermediate",
            "produces_for": ["R0003"],
            "reads": [],
            "write_condition": "P_1001",
        }, {}, _rs_sources())
        assert rule["step_type"] == "aggregate"
        assert rule["target_role"] == "intermediate"
        assert rule["produces_for"] == ["R0003"]
        assert rule["reads"] == []
        assert rule["write_condition"] == "P_1001"

    def test_write_condition_defaults_empty(self):
        """旧 design_decisions 无 write_condition -> 默认空。"""
        rule, _ = build_rule(
            {"rule_code": "R0001", "source_aliases": []}, {}, _rs_sources())
        assert rule["write_condition"] == ""

    def test_merge_rule_reads_carried(self):
        """merge 规则的 reads（读哪些中间表）正确搬入。"""
        rule, _ = build_rule({
            "rule_code": "R0003",
            "source_aliases": [],
            "step_type": "merge",
            "target_role": "target",
            "produces_for": [],
            "reads": ["tmp1", "tmp2"],
        }, {}, _rs_sources())
        assert rule["step_type"] == "merge"
        assert rule["target_role"] == "target"
        assert rule["reads"] == ["tmp1", "tmp2"]

    def test_none_produces_for_normalized_to_empty(self):
        """produces_for 为 None（YAML 留空常见）-> 归一为 []，不出 None。"""
        rule, _ = build_rule({
            "rule_code": "R0001", "source_aliases": [],
            "produces_for": None, "reads": None,
        }, {}, _rs_sources())
        assert rule["produces_for"] == []
        assert rule["reads"] == []


# ============================================================
# 调度任务路径（schedule_config）：load_schedule_config / resolve_schedule_path
# ============================================================

from assemble_ts import load_schedule_config, resolve_schedule_path


class TestLoadScheduleConfig:
    def test_missing_file_returns_empty(self):
        assert load_schedule_config("/nonexistent/schedule_config.json") == {}

    def test_loads_valid_config(self, tmp_path):
        cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "schema_mappings": {"fin": {"project_name": "FIN_DAILY"}},
        }
        p = tmp_path / "schedule_config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        result = load_schedule_config(str(p))
        assert result["default"]["project_name"] == "SRP_DAILY"

    def test_filters_comment_fields(self, tmp_path):
        """_comment / _structure 等说明字段被过滤掉。"""
        cfg = {
            "_comment": "说明",
            "_structure": "结构",
            "default": {"project_name": "P"},
        }
        p = tmp_path / "schedule_config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        result = load_schedule_config(str(p))
        assert "_comment" not in result
        assert "_structure" not in result
        assert "default" in result

    def test_invalid_json_returns_empty(self, tmp_path):
        p = tmp_path / "schedule_config.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert load_schedule_config(str(p)) == {}


class TestResolveSchedulePath:
    def test_empty_config_returns_empty(self):
        assert resolve_schedule_path({}, "dws", "f") == {
            "project_name": "", "task_group": ""}

    def test_default_used(self):
        cfg = {"default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"}}
        r = resolve_schedule_path(cfg, "dws", "f")
        assert r["project_name"] == "SRP_DAILY"
        assert r["task_group"] == "GROUP_SPRD"

    def test_schema_mapping_overrides_default(self):
        cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "schema_mappings": {"fin": {"project_name": "FIN_DAILY", "task_group": "GROUP_FIN"}},
        }
        r = resolve_schedule_path(cfg, "fin", "f")
        assert r["project_name"] == "FIN_DAILY"
        assert r["task_group"] == "GROUP_FIN"

    def test_unknown_schema_uses_default(self):
        cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "schema_mappings": {"fin": {"project_name": "FIN_DAILY"}},
        }
        r = resolve_schedule_path(cfg, "unknown", "f")
        assert r["project_name"] == "SRP_DAILY"

    def test_dq_override(self):
        """dq 任务类型走 dq_override 段。"""
        cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "dq_override": {"project_name": "SRP_DQ", "task_group": "GROUP_DQ"},
        }
        r = resolve_schedule_path(cfg, "dws", "dq")
        assert r["project_name"] == "SRP_DQ"
        assert r["task_group"] == "GROUP_DQ"

    def test_init_override(self):
        """init 任务类型走 init_override 段。"""
        cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "init_override": {"project_name": "SRP_INIT", "task_group": "GROUP_INIT"},
        }
        r = resolve_schedule_path(cfg, "dws", "init")
        assert r["project_name"] == "SRP_INIT"

    def test_override_priority_over_schema(self):
        """override > schema_mappings > default。"""
        cfg = {
            "default": {"project_name": "DEF"},
            "schema_mappings": {"fin": {"project_name": "FIN"}},
            "dq_override": {"project_name": "DQ"},
        }
        r = resolve_schedule_path(cfg, "fin", "dq")
        assert r["project_name"] == "DQ", "override 应优先于 schema"

    def test_no_override_for_f_view(self):
        """f/view 不走 override 段（只有 dq/init 有 override）。"""
        cfg = {
            "default": {"project_name": "DEF", "task_group": "G_DEF"},
            "dq_override": {"project_name": "DQ", "task_group": "G_DQ"},
        }
        r = resolve_schedule_path(cfg, "dws", "f")
        assert r["project_name"] == "DEF", "f 不应被 dq_override 影响"
        assert r["task_group"] == "G_DEF"


# ============================================================
# build_meta：tasks 段带 project_name/task_group
# ============================================================

import json
from assemble_ts import build_meta


def _rs_input_for_meta(schema="dws", f_table="dwb_test_f", i_view="dwb_test_i"):
    """构造 build_meta 的最小 rs_input。"""
    return {
        "meta": {
            "target": {
                "f_table": {"schema": schema, "table": f_table, "cn": "测试"},
                "i_view": {"schema": schema, "table": i_view, "cn": "测试"},
            },
            "grain": "",
        },
        "source_tables": [],
        "schedule": {},
    }


class TestBuildMetaTaskPath:
    """build_meta 给每个 task 填 project_name/task_group。"""

    def test_tasks_have_project_group(self, monkeypatch):
        """有 schedule_config + dq_rules 非空时，tasks.f/view/dq 都有 project_name/task_group。"""
        sched_cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "dq_override": {"project_name": "SRP_DQ", "task_group": "GROUP_DQ"},
        }
        monkeypatch.setattr("assemble_ts.load_schedule_config", lambda: sched_cfg)
        decisions = {"schedule": {"cron": "0 30 3 * * ?"},
                     "dq_rules": [{"scope": "表级", "check_type": "重复数据检查",
                                   "rule_name": "主键唯一", "rule_desc": "id 不重复"}]}
        meta = build_meta(_rs_input_for_meta(), decisions)
        tasks = meta["schedule"]["tasks"]
        assert tasks["f"]["project_name"] == "SRP_DAILY"
        assert tasks["f"]["task_group"] == "GROUP_SPRD"
        assert tasks["view"]["project_name"] == "SRP_DAILY"
        # dq 走 dq_override（仅 dq_rules 非空时才建）
        assert tasks["dq"]["project_name"] == "SRP_DQ"
        assert tasks["dq"]["task_group"] == "GROUP_DQ"

    def test_no_config_empty_path(self, monkeypatch):
        """无 schedule_config（旧环境）-> project/task_group 为空串，不报错（向后兼容）。"""
        monkeypatch.setattr("assemble_ts.load_schedule_config", lambda: {})
        meta = build_meta(_rs_input_for_meta(), {"schedule": {"cron": "0 30 3 * * ?"}})
        tasks = meta["schedule"]["tasks"]
        assert tasks["f"]["project_name"] == ""
        assert tasks["f"]["task_group"] == ""

    def test_designer_override_wins(self, monkeypatch):
        """designer 的 task_project_override 最优先（如初始化任务组）。"""
        sched_cfg = {"default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"}}
        monkeypatch.setattr("assemble_ts.load_schedule_config", lambda: sched_cfg)
        decisions = {"schedule": {
            "cron": "0 30 3 * * ?",
            "task_project_override": {
                "dq": {"project_name": "CUSTOM_DQ", "task_group": "CUSTOM_GDQ"},
            },
        }, "dq_rules": [{"scope": "表级", "check_type": "重复数据检查",
                         "rule_name": "主键唯一", "rule_desc": "id 不重复"}]}
        meta = build_meta(_rs_input_for_meta(), decisions)
        tasks = meta["schedule"]["tasks"]
        assert tasks["dq"]["project_name"] == "CUSTOM_DQ"
        assert tasks["dq"]["task_group"] == "CUSTOM_GDQ"
        # f 不受影响，仍用默认
        assert tasks["f"]["project_name"] == "SRP_DAILY"

    def test_schema_mapping_applied(self, monkeypatch):
        """target schema 在 schema_mappings 里 -> 用 schema 的配置。"""
        sched_cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "schema_mappings": {"fin": {"project_name": "FIN_DAILY", "task_group": "GROUP_FIN"}},
        }
        monkeypatch.setattr("assemble_ts.load_schedule_config", lambda: sched_cfg)
        meta = build_meta(_rs_input_for_meta(schema="fin"), {"schedule": {"cron": "x"}})
        assert meta["schedule"]["tasks"]["f"]["project_name"] == "FIN_DAILY"
        assert meta["schedule"]["tasks"]["f"]["task_group"] == "GROUP_FIN"


# ============================================================
# 五层校验契约测试（run_all_validations）
# ============================================================

from conftest import (make_rs_input, make_design_decisions,
                      make_incremental_rs_input, make_incremental_decisions,
                      make_accumulate_decisions, make_dq_rs_input)


def _run(decisions, rs_input=None):
    """便捷：跑全量校验，返回 ValidationResult。"""
    if rs_input is None:
        rs_input = make_rs_input()
    field_map = {fm["target_column"]: fm for fm in rs_input["field_mappings"]}
    return run_all_validations(decisions, rs_input, field_map)


def _codes(vr, layer=None):
    """提取触发的校验 code 列表（可选按层过滤）。"""
    return [info["code"] for info in vr.items if layer is None or info["layer"] == layer]


def _level_of(vr, code):
    """返回某 code 的 level（hard/soft/warn），不存在返回 None。"""
    for info in vr.items:
        if info["code"] == code:
            return info["level"]
    return None


class TestLayer0Anchor:
    """第0层 锚点（N1-N4）。"""

    def test_valid_defaults_pass(self):
        """默认 decisions（含 business_key_design）应无 N1-N4 报错。"""
        vr = _run(make_design_decisions())
        for code in ("N1", "N2", "N3", "N4"):
            assert code not in _codes(vr), f"{code} 不该触发"

    def test_n1_grain_empty_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["grain"] = {"input": "", "output": ""}
        vr = _run(dd)
        assert "N1" in _codes(vr)

    def test_n2_business_key_empty_reports(self):
        dd = make_design_decisions(business_key=[])
        vr = _run(dd)
        assert "N2" in _codes(vr)

    def test_n3_no_reason_reports(self):
        dd = make_design_decisions(business_key_design={"input_key": ["id"], "adjusted": False, "reason": ""})
        vr = _run(dd)
        assert "N3" in _codes(vr)

    def test_n3_adjusted_no_reason_reports(self):
        dd = make_design_decisions(business_key_design={"input_key": ["id"], "adjusted": True, "reason": ""})
        vr = _run(dd)
        assert "N3" in _codes(vr)

    def test_n4_business_key_not_in_table_reports(self):
        dd = make_design_decisions(business_key=["nonexistent_field"])
        vr = _run(dd)
        assert "N4" in _codes(vr)


class TestLayer2Path:
    """第2层 加工路径（N6-N12, N10b/c/d）。"""

    def test_valid_single_rule_passes(self):
        vr = _run(make_design_decisions())
        for code in ("N6", "N7", "N8", "N9", "N10"):
            assert code not in _codes(vr, "L2")

    def test_n6_bad_step_type_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["step_type"] = "incr"
        vr = _run(dd)
        assert "N6" in _codes(vr, "L2")

    def test_n7_bad_target_role_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["target_role"] = "stage"
        vr = _run(dd)
        assert "N7" in _codes(vr, "L2")

    def test_n8_intermediate_merge_conflict_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["step_type"] = "merge"
        dd["rules"][0]["target_role"] = "intermediate"
        vr = _run(dd)
        assert "N8" in _codes(vr, "L2")

    def test_n8_full_intermediate_allowed(self):
        """full + intermediate（非聚合中间加工）应允许，不报 N8。"""
        dd = make_design_decisions()
        dd["rules"][0]["step_type"] = "full"
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["produces_for"] = ["R0002"]
        dd["rules"].append({
            "rule_code": "R0002", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 2, "target_table": "dws.dwb_test_f", "is_view_step": False,
            "step_type": "full", "target_role": "target",
            "produces_for": [], "reads": ["dws.dwb_test_f"],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "s", "output": "t", "change": "无"},
        })
        # 注意：上面 reads 引用自己（单规则场景），调整构造合理的两步
        dd["rules"][0]["target_table"] = "dws.tmp1"
        dd["rules"][1]["reads"] = ["dws.tmp1"]
        vr = _run(dd)
        assert "N8" not in _codes(vr, "L2")

    def test_n9_intermediate_no_produces_for_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["produces_for"] = []
        vr = _run(dd)
        assert "N9" in _codes(vr, "L2")

    def test_n10b_dangling_intermediate_reports(self):
        """中间表产出但无下游 reads 引用 → N10b。"""
        dd = make_design_decisions()
        dd["rules"][0]["target_table"] = "dws.tmp1"
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["produces_for"] = ["R0002"]
        dd["rules"][0]["step_type"] = "aggregate"
        dd["rules"].append({
            "rule_code": "R0002", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 2, "target_table": "dws.dwb_test_f", "is_view_step": False,
            "step_type": "full", "target_role": "target",
            "produces_for": [], "reads": [],  # 没读 tmp1
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "s", "output": "t", "change": "无"},
        })
        vr = _run(dd)
        assert "N10b" in _codes(vr, "L2")

    def test_n10c_wrong_sequence_reports(self):
        """produces_for A→B 但 seq(A) >= seq(B) → N10c。"""
        dd = make_design_decisions()
        dd["rules"][0]["target_table"] = "dws.tmp1"
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["step_type"] = "aggregate"
        dd["rules"][0]["exec_sequence"] = 2  # 故意排在后面
        dd["rules"][0]["produces_for"] = ["R0002"]
        dd["rules"].append({
            "rule_code": "R0002", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1,  # 排在前面
            "target_table": "dws.dwb_test_f", "is_view_step": False,
            "step_type": "full", "target_role": "target",
            "produces_for": [], "reads": ["dws.tmp1"],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "s", "output": "t", "change": "无"},
        })
        vr = _run(dd)
        assert "N10c" in _codes(vr, "L2")

    def test_n10d_cycle_reports(self):
        """循环依赖 A→B→A → N10d。"""
        dd = make_design_decisions()
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["step_type"] = "aggregate"
        dd["rules"][0]["produces_for"] = ["R0002"]
        dd["rules"].append({
            "rule_code": "R0002", "rule_name": "环", "scenario": "default",
            "exec_sequence": 2, "target_table": "dws.tmp2", "is_view_step": False,
            "step_type": "aggregate", "target_role": "intermediate",
            "produces_for": ["R0001"], "reads": [],
            "field_targets": ["id"], "field_logics": {},
        })
        vr = _run(dd)
        assert "N10d" in _codes(vr, "L2")

    def test_n11_produces_for_nonexistent_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["target_role"] = "intermediate"
        dd["rules"][0]["produces_for"] = ["R9999"]
        vr = _run(dd)
        assert "N11" in _codes(vr, "L2")

    def test_n12_reads_nonexistent_table_reports(self):
        dd = make_design_decisions()
        dd["rules"][0]["reads"] = ["dws.nonexistent_tmp"]
        vr = _run(dd)
        assert "N12" in _codes(vr, "L2")


class TestAccumulateBuildMode:
    """累积共建场景（C9 放行 + N26/N27）。"""

    def _acc_rs_input(self):
        """造含 a/b/c/d/e 字段的 rs_input（配合 make_accumulate_decisions）。"""
        fields = []
        for name in ("a", "b", "c", "d", "e"):
            fields.append({
                "source_table": "ods_src_f", "source_column": name, "source_type": "varchar",
                "transform_rule": "直接复制", "transform_detail": "-",
                "target_column": name, "target_column_cn": name, "target_type": "VARCHAR(50)",
                "source_alias": "t", "remark": "",
            })
        # 审计字段也加上，覆盖目标表
        for name, tt, expr in [("del_flag", "NVARCHAR(1)", "'N'"),
                               ("crt_cycle_id", "BIGINT", "'${P_CYCLE_ID}'"),
                               ("last_upd_cycle_id", "BIGINT", "'${P_CYCLE_ID}'"),
                               ("dw_last_update_date", "TIMESTAMP(0)", "CURRENT_TIMESTAMP")]:
            fields.append({
                "transform_rule": "赋值", "transform_detail": expr,
                "target_column": name, "target_column_cn": name, "target_type": tt,
                "remark": "审计字段",
            })
        return make_rs_input(table="dwb_acc_i", fields=fields)

    def test_accumulate_overlap_passes_c9(self):
        """累积共建：两规则同字段(b/c)重叠，标了 build_mode=accumulate → C9 不报。"""
        rs = self._acc_rs_input()
        dd = make_accumulate_decisions()
        vr = _run(dd, rs)
        # C9 是存量校验，经 legacy_errors 进 L1。检查不含"重复分配"
        l1_msgs = [i["msg"] for i in vr.items if i["layer"] == "L1"]
        assert not any("重复分配" in m for m in l1_msgs), f"累积共建不该报 C9: {l1_msgs}"

    def test_transform_overlap_reports_c9(self):
        """没标 accumulate（默认 transform），同字段重叠 → C9 报（带 accumulate 提示）。"""
        rs = self._acc_rs_input()
        dd = make_accumulate_decisions()
        dd["tables"]["dwb_acc_tmp1"]["build_mode"] = "transform"  # 改回 transform
        vr = _run(dd, rs)
        l1_msgs = [i["msg"] for i in vr.items if i["layer"] == "L1"]
        assert any("重复分配" in m and "accumulate" in m for m in l1_msgs)

    def test_n27_overlap_no_dedup_warns(self):
        """累积共建有重叠字段但没声明 dedup_strategy → N27 warn。"""
        rs = self._acc_rs_input()
        dd = make_accumulate_decisions()
        # 删掉 R0002 的 dedup_strategy
        dd["rules"][1]["dedup_strategy"] = None
        vr = _run(dd, rs)
        assert "N27" in _codes(vr, "LA")

    def test_n26_dedup_key_empty_reports(self):
        """声明了 dedup_strategy 但 key 空 → N26 报。"""
        rs = self._acc_rs_input()
        dd = make_accumulate_decisions()
        dd["rules"][1]["dedup_strategy"]["key"] = []
        vr = _run(dd, rs)
        assert "N26" in _codes(vr, "LA")

    def test_self_reference_reads_not_cycle(self):
        """自引用 reads（读自己 target_table）不触发循环检查。"""
        rs = self._acc_rs_input()
        dd = make_accumulate_decisions()
        vr = _run(dd, rs)
        assert "N10d" not in _codes(vr, "L2"), "自引用不该当循环"


class TestLayer3Incremental:
    """第3层 增量（N14-N17）。"""

    def test_valid_multi_driver_passes(self):
        """两张驱动表 + 两个 extract + merge → 无硬阻断。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([
            {"key": "update_time", "table": "ods_test_f"},
            {"key": "dt", "table": "ods_pay_f"},
        ])
        # 补 params 声明增量参数
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        vr = _run(dd, rs)
        # N14(完全没管) / N15(extract填全) 不该触发
        for code in ("N14", "N15"):
            msgs = [i['msg'] for i in vr.items if i['code'] == code]
            assert code not in _codes(vr, "L3"), f"{code} 不该触发: {msgs}"

    def test_n14_completely_no_incremental_processing_reports(self):
        """标了增量但完全没增量处理（无 extract、无 incremental 段、source 不涉驱动表）→ N14。"""
        rs = make_incremental_rs_input()
        # 用一个普通的 full 规则，source 是别的表（不涉驱动表），完全没增量处理
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "全量", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f", "is_view_step": False,
            "step_type": "full", "target_role": "target",
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
            "source_aliases": ["other"],  # 不是驱动表
        }])
        # rs_input 的 source_tables 改成别的表（不涉驱动表）
        rs["source_tables"] = [{"source_schema": "ods", "source_table": "ods_other_f",
                                "source_table_cn": "其他", "source_alias": "other"}]
        vr = _run(dd, rs)
        assert "N14" in _codes(vr, "L3")

    def test_n14_partial_increment_still_ok(self):
        """只做一个 extract（漏了另一张驱动表）不再报 N14——松绑后是 designer 设计自由。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([
            {"key": "update_time", "table": "ods_test_f"},
            # 没做 ods_pay_f 的 extract，但做过增量处理 → 不触发 N14
        ])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        vr = _run(dd, rs)
        assert "N14" not in _codes(vr, "L3"), "有增量处理就不该报 N14（模式自由）"

    def test_n15_extract_missing_key_reports(self):
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["rules"][0]["incremental"]["key"] = ""  # 清空 key
        vr = _run(dd, rs)
        assert "N15" in _codes(vr, "L3")

    def test_n16_driver_uncovered_warns(self):
        """驱动表增量字段未在增量范围里出现 → N16 warn（降级，不阻断）。"""
        rs = make_incremental_rs_input()
        # 两个 extract 但都用同一个 key，另一张驱动表的 key 没覆盖
        dd = make_incremental_decisions([
            {"key": "update_time", "table": "ods_test_f"},
            {"key": "update_time", "table": "ods_pay_f"},  # 应该是 dt，这里故意用 update_time
        ])
        vr = _run(dd, rs)
        warns = vr.warnings()
        assert any(c == "N16" for _, c, _ in warns), "N16 应是 warn"
        # 且不是硬阻断
        hard = vr.hard_errors()
        assert not any(c == "N16" for _, c, _ in hard), "N16 不该是硬阻断（已降 warn）"

    def test_n22_undeclared_param_reports(self):
        """增量 filter 引用未声明参数 → N22。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        # 不声明 BIZ_DATE_START/BIZ_DATE_END
        dd["params"] = []
        vr = _run(dd, rs)
        assert "N22" in _codes(vr, "LC")


class TestLayer4Engineering:
    """第4层 工程（N18-N21）+ cron。"""

    def test_valid_defaults_pass(self):
        vr = _run(make_design_decisions())
        for code in ("N18", "N19", "N20", "N21"):
            assert code not in _codes(vr, "L4")

    def test_n18_bad_schedule_type_reports(self):
        dd = make_design_decisions()
        dd["schedule"]["schedule_type"] = "weekly"
        vr = _run(dd)
        assert "N18" in _codes(vr, "L4")

    def test_n19_bad_cron_segments_reports(self):
        dd = make_design_decisions()
        dd["schedule"]["cron"] = "0 3 * * *"  # 5 段
        vr = _run(dd)
        assert "N19" in _codes(vr, "L4")

    def test_n19_valid_quartz_passes(self):
        dd = make_design_decisions()
        dd["schedule"]["cron"] = "0 30 3 * * ?"
        vr = _run(dd)
        assert "N19" not in _codes(vr, "L4")

    def test_n19_cron_out_of_range_reports(self):
        dd = make_design_decisions()
        dd["schedule"]["cron"] = "99 30 3 * * ?"  # 秒越界
        vr = _run(dd)
        assert "N19" in _codes(vr, "L4")

    def test_n20_bad_distribute_type_reports(self):
        dd = make_design_decisions(tables={"dwb_test_f": {"distribute_type": "RANDOM", "distribution_key": ["id"]}})
        vr = _run(dd)
        assert "N20" in _codes(vr, "L4")

    def test_n21_dist_key_not_in_table_reports(self):
        """分布键字段不在所属表 → N21。"""
        dd = make_design_decisions(tables={"dwb_test_f": {"distribution_key": ["nonexistent"], "distribute_type": "HASH"}})
        vr = _run(dd)
        assert "N21" in _codes(vr, "L4")

    def test_n21_dist_key_in_own_table_passes(self):
        """分布键字段在自己表里 → 不报 N21（不跨表）。"""
        dd = make_design_decisions(tables={"dwb_test_f": {"distribution_key": ["id"], "distribute_type": "HASH"}})
        vr = _run(dd)
        assert "N21" not in _codes(vr, "L4")


class TestQuartzCron:
    """Quartz cron 校验函数单测。"""

    def test_valid_standard(self):
        assert validate_quartz_cron("0 30 3 * * ?") == []

    def test_valid_with_modifiers(self):
        assert validate_quartz_cron("0 0/15 * * * ?") == []
        assert validate_quartz_cron("0 0 9 ? * MON-FRI") == []

    def test_wrong_segments(self):
        errs = validate_quartz_cron("0 3 * * *")
        assert len(errs) == 1 and "6 段" in errs[0]

    def test_out_of_range(self):
        errs = validate_quartz_cron("99 30 3 * * ?")
        assert any("越界" in e for e in errs)

    def test_empty(self):
        assert len(validate_quartz_cron("")) >= 1

    def test_invalid_char(self):
        # @ 是 Quartz cron 不允许的字符（合法字符集：数字/字母/* ? , - / L W #）
        errs = validate_quartz_cron("0 30 3 @ * ?")
        assert any("非法字符" in e for e in errs)


class TestLayerCross:
    """横切（N23-N25）。"""

    def test_n25_design_approach_empty_reports(self):
        dd = make_design_decisions()
        dd["complexity_analysis"]["design_approach"] = ""
        vr = _run(dd)
        assert "N25" in _codes(vr, "LC")

    def test_n23_dependency_nonexistent_warns(self):
        dd = make_design_decisions()
        dd["data_flow"]["dependencies"] = [{"from": "R9999", "to": "R0001"}]
        vr = _run(dd)
        warns = vr.warnings()
        assert any(c == "N23" for _, c, _ in warns)


class TestErrorGrouping:
    """校验报错按层分组输出。"""

    def test_format_report_groups_by_layer(self):
        dd = make_design_decisions(business_key=[])  # 触发 N2
        dd["schedule"]["cron"] = "0 3 * * *"  # 触发 N19
        vr = _run(dd)
        report = vr.format_report()
        assert "[第0层-锚点]" in report
        assert "[第4层-工程保障]" in report

    def test_format_report_no_errors_empty(self):
        vr = _run(make_design_decisions())
        # 可能有 warn 但没 hard
        report = vr.format_report()
        assert "阻断" not in report


class TestDQDriven:
    """DQ 完全跟随 RS（N_DQ1-N_DQ3）。designer 是翻译者，不是搬运工。

    RS 有 DQ 需求 → designer 翻译产 dq_rules；RS 无 → dq_rules 留空。
    """

    def test_rs_has_dq_but_empty_blocks(self):
        """N_DQ1 硬阻断：RS 有 DQ 需求但 designer 没翻译产 dq_rules（漏翻译根因）。"""
        rs = make_dq_rs_input()  # 2 条 DQ 需求
        dd = make_design_decisions()  # dq_rules 默认空
        vr = _run(dd, rs)
        assert "N_DQ1" in _codes(vr, "LD")
        assert _level_of(vr, "N_DQ1") == "hard"

    def test_rs_has_dq_translated_passes(self):
        """RS 有 DQ + dq_rules 已翻译（条数 == RS）→ 通过，无 N_DQ1/2/3。"""
        rs = make_dq_rs_input()  # 2 条
        dd = make_design_decisions(dq_rules=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "订单金额非空",
             "rule_desc": "检查 dwb_dqtest_f.order_amount IS NOT NULL，空值告警"},
            {"scope": "表级", "check_type": "重复数据检查", "rule_name": "主键唯一",
             "rule_desc": "检查 id 重复，GROUP BY id HAVING COUNT(*)>1"},
        ])
        vr = _run(dd, rs)
        for code in ("N_DQ1", "N_DQ2", "N_DQ3"):
            assert code not in _codes(vr, "LD"), f"{code} 不该触发"

    def test_rs_has_dq_more_translated_passes(self):
        """翻译后条数可增加（一条拆多条），≥ RS 通过（不触发 N_DQ2）。"""
        rs = make_dq_rs_input(dq_needs=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "金额非空", "rule_desc": "x"},
        ])
        dd = make_design_decisions(dq_rules=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "金额非空", "rule_desc": "a"},
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "数量非空", "rule_desc": "b"},
        ])
        vr = _run(dd, rs)
        assert "N_DQ2" not in _codes(vr, "LD")

    def test_rs_has_dq_partial_warns(self):
        """N_DQ2 warn：RS 有 DQ 但 dq_rules 条数少于 RS（可能漏翻译）。"""
        rs = make_dq_rs_input()  # 2 条
        dd = make_design_decisions(dq_rules=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "金额非空", "rule_desc": "x"},
        ])  # 只翻译 1 条
        vr = _run(dd, rs)
        assert "N_DQ2" in _codes(vr, "LD")
        assert _level_of(vr, "N_DQ2") == "warn"

    def test_no_rs_dq_empty_passes(self):
        """RS 无 DQ + dq_rules 空 → 通过（不产 DQ，无 N_DQ1/2/3）。"""
        rs = make_rs_input()  # 默认无 DQ
        dd = make_design_decisions()  # dq_rules 空
        vr = _run(dd, rs)
        for code in ("N_DQ1", "N_DQ2", "N_DQ3"):
            assert code not in _codes(vr, "LD")

    def test_no_rs_dq_but_added_warns(self):
        """N_DQ3 warn：RS 无 DQ 但 designer 自行加了（DQ 是业务决策归 RS）。"""
        rs = make_rs_input()  # 无 DQ
        dd = make_design_decisions(dq_rules=[
            {"scope": "表级", "check_type": "重复数据检查", "rule_name": "主键唯一", "rule_desc": "x"},
        ])
        vr = _run(dd, rs)
        assert "N_DQ3" in _codes(vr, "LD")
        assert _level_of(vr, "N_DQ3") == "warn"

    def test_dq_task_absent_when_empty(self):
        """dq_rules 空 → build_meta 不建 tasks["dq"]（RS 无 DQ，无调度任务）。"""
        rs = make_rs_input()
        dd = make_design_decisions()  # dq_rules 空
        meta = build_meta(rs, dd)
        tasks = meta["schedule"]["tasks"]
        assert "dq" not in tasks

    def test_dq_task_present_when_nonempty(self):
        """dq_rules 非空 → build_meta 建 tasks["dq"]（RS 有 DQ，有调度任务）。"""
        rs = make_rs_input()
        dd = make_design_decisions(dq_rules=[
            {"scope": "表级", "check_type": "重复数据检查", "rule_name": "主键唯一", "rule_desc": "x"},
        ])
        meta = build_meta(rs, dd)
        tasks = meta["schedule"]["tasks"]
        assert "dq" in tasks
