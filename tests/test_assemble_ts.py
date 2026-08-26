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
                      make_accumulate_decisions, make_dq_rs_input,
                      make_derive_init_decisions, make_explicit_init_decisions)
from assemble_ts import assemble_ts as do_assemble, render_md, build_field


def _run(decisions, rs_input=None):
    """便捷：跑全量校验，返回 ValidationResult。"""
    if rs_input is None:
        rs_input = make_rs_input()
    field_map = {fm["target_column"]: fm for fm in rs_input["field_mappings"]}
    return run_all_validations(decisions, rs_input, field_map)


def _codes(vr, layer=None):
    """提取触发的校验 code 列表（可选按层过滤）。"""
    return [info["code"] for info in vr.items if layer is None or info["layer"] == layer]


class TestRefSkeleton:
    """口径引用骨架：N36 裸引用硬拦 / N37 翻译丢引用对账 / source_fields 装配补全。

    真实案例：del_flag 口径引用三字段，design_logic 只写一个 → coder 丢两个字段。
    """

    @staticmethod
    def _rs():
        fms = [
            {"target_column": "id", "transform_rule": "直接复制", "transform_detail": "-",
             "source_alias": "a", "source_column": "id", "source_table": "ods_a"},
            {"target_column": "d1", "transform_rule": "直接复制", "transform_detail": "-",
             "source_alias": "u", "source_column": "delete_flag", "source_table": "ods_u"},
            {"target_column": "d2", "transform_rule": "直接复制", "transform_detail": "-",
             "source_alias": "a", "source_column": "del_flag", "source_table": "ods_a"},
            {"target_column": "d3", "transform_rule": "直接复制", "transform_detail": "-",
             "source_alias": "u", "source_column": "del_flag", "source_table": "ods_u"},
            {"target_column": "flag", "transform_rule": "数据加工",
             "transform_detail": "当 a.del_flag 和 delete_flag 以及 u.del_flag 都为 n 或空",
             "source_alias": "a", "source_column": "del_flag", "source_table": "ods_a",
             "_raw_refs": ["del_flag", "delete_flag"]},
        ]
        return fms

    @staticmethod
    def _dec(logic):
        cols = ["id", "d1", "d2", "d3", "flag"]
        return make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": cols, "field_logics": {"flag": logic},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])

    def test_fully_qualified_and_covered_passes(self):
        rs = {"field_mappings": self._rs(), "source_tables": []}
        vr = _run(self._dec("a.del_flag、u.delete_flag、u.del_flag 均为 N 或空 → N，否则 Y"), rs)
        assert "N36" not in _codes(vr) and "N37" not in _codes(vr)

    def test_bare_reference_hard_blocked(self):
        vr = _run(self._dec("a.del_flag 和 delete_flag 为 N → N"),
                  {"field_mappings": self._rs(), "source_tables": []})
        n36 = [i for i in vr.items if i["code"] == "N36"]
        assert n36 and n36[0]["level"] == "hard" and "delete_flag" in n36[0]["msg"]

    def test_dropped_reference_warns(self):
        vr = _run(self._dec("a.del_flag 为 N 或空 → N"),
                  {"field_mappings": self._rs(), "source_tables": []})
        n37 = [i for i in vr.items if i["code"] == "N37"]
        assert n37 and "delete_flag" in n37[0]["msg"]

    def test_source_fields_completed_from_logic(self):
        fms = self._rs()
        registry = {}
        for f in fms:
            al, c = (f.get("source_alias") or "").lower(), (f.get("source_column") or "").lower()
            if al and c:
                registry.setdefault((al, c), f)
        f = build_field(
            next(x for x in fms if x["target_column"] == "flag"),
            "a.del_flag、u.delete_flag、u.del_flag 均为 N 或空 → N，否则 Y",
            set(), ref_registry=registry)
        sf = {(s["alias"], s["field"]) for s in f["source_fields"]}
        assert {("a", "del_flag"), ("u", "delete_flag"), ("u", "del_flag")} <= sf


class TestAssignTranslationGate:
    """N35 赋值翻译闸：错标识别后置到 designer 翻译之后（输入层判不了自然语言——
    "当xx条件赋1"的 xx 可能是字段也可能是描述），装配层做过程检查：
    赋值 + 非标准字面量 + designer 没写 field_logics → hard。标准审计字段豁免
    （语义约定固定，值按 STANDARD_AUDIT_TEMPLATE 归一，无需 designer 动作）。"""

    @staticmethod
    def _rs_with_assign(detail):
        return make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
            {"source_table": "ods_ht_f", "source_column": "", "source_type": "",
             "transform_rule": "赋值", "transform_detail": detail,
             "target_column": "flag", "target_column_cn": "标记", "target_type": "varchar(1)",
             "source_alias": "", "remark": ""},
        ], has_audit=True)

    @staticmethod
    def _dec(flag_logic=None):
        return make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["a", "flag", "del_flag", "crt_cycle_id",
                              "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {"flag": flag_logic} if flag_logic else {},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])

    def test_untranslated_nontrivial_assign_blocked(self):
        """条件是描述（非字段名）——输入层判不了，但 designer 没翻译就是可判的过程缺失。"""
        vr = _run(self._dec(), self._rs_with_assign("当订单状态为已完成时赋1，否则赋2"))
        assert "N35" in _codes(vr)
        n35 = [i for i in vr.items if i["code"] == "N35"][0]
        assert n35["level"] == "hard" and n35["layer"] == "L1" and "flag" in n35["msg"]

    def test_translated_assign_passes(self):
        vr = _run(self._dec("ht.a=1 置 Y 否则 N"),
                  self._rs_with_assign("CASE WHEN ht.a=1 THEN 'Y' ELSE 'N' END"))
        assert "N35" not in _codes(vr)

    def test_trivial_assign_passes_without_translation(self):
        vr = _run(self._dec(), self._rs_with_assign("'N'"))
        assert "N35" not in _codes(vr)

    def test_standard_audit_exempt_and_normalized(self):
        """审计字段豁免 N35；非标准写法（"传参"/"新增时间戳"）按模板标准值归一。"""
        from assemble_ts import build_design, build_field
        from dws_standards import STANDARD_AUDIT_TEMPLATE
        rs = make_rs_input(has_audit=True)
        for fm in rs["field_mappings"]:
            if fm["target_column"] == "crt_cycle_id":
                fm["transform_detail"] = "传参"
            if fm["target_column"] == "dw_last_update_date":
                fm["transform_detail"] = "新增时间戳"
        assert "N35" not in _codes(_run(make_design_decisions(), rs))
        d = build_design(make_design_decisions(), rs)
        assert d["audit_fields"]["crt_cycle_id"]["default"] == \
            STANDARD_AUDIT_TEMPLATE["crt_cycle_id"]["default"]
        assert d["audit_fields"]["dw_last_update_date"]["default"] == "CURRENT_TIMESTAMP"
        fm_crt = next(fm for fm in rs["field_mappings"] if fm["target_column"] == "crt_cycle_id")
        f = build_field(fm_crt, None, set())
        assert f["design_logic"] == \
            f"固定赋值 {STANDARD_AUDIT_TEMPLATE['crt_cycle_id']['default']}"


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
            "exec_sequence": 2, "target_table": "dws.dwb_test_f",
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
            "exec_sequence": 2, "target_table": "dws.dwb_test_f",
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
            "target_table": "dws.dwb_test_f",
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
            "exec_sequence": 2, "target_table": "dws.tmp2",
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
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
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

    def test_single_full_rule_on_incremental_asset_blocked(self):
        """回归：单规则 full 直灌增量资产（规则 source 就是驱动表、无 incremental 段）。

        真实案例：designer 拿全量心智装增量数据——单规则 + step_type=full +
        truncate_table。旧版 N14 的第三个析取（source 涉驱动表恒为真）让它
        形同虚设；现在 N14/N28/N_INIT2 三道硬闸全部拦截。
        """
        rs = make_incremental_rs_input()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "全量直灌", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target", "load_mode": "truncate_table",
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
            "source_aliases": ["t"],  # ★ 恰是驱动表（旧 N14 的死析取）
        }])
        vr = _run(dd, rs)
        codes = _codes(vr, "L3")
        assert "N14" in codes, "source 涉驱动表不该再让 N14 失明（死析取已删）"
        assert "N28" in codes, "单规则增量资产必须被 N28 拦"
        assert "N_INIT2" in codes, "RS 锚定的终态 truncate 必须被 N_INIT2 拦"
        init2_msgs = [i["msg"] for i in vr.items if i["code"] == "N_INIT2"]
        assert any("RS 标了增量" in m for m in init2_msgs), \
            f"N_INIT2 报错应说明锚点是 RS 增量声明: {init2_msgs}"

    def test_n28_single_incremental_rule_blocked_even_wellformed(self):
        """单规则即使形态'正确'（带 incremental 段 + merge 写入）也拦——至少两个规则是结构铁律。"""
        rs = make_incremental_rs_input()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则增量", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target", "load_mode": "merge_into",
            "write_condition": "T.id=T1.id",
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
            "incremental": {"key": "update_time",
                            "filter": "update_time >= '${P_START_DATE}' AND update_time < '${P_END_DATE}'",
                            "init_filter": "1=1", "init_time_range": "ALL"},
        }])
        vr = _run(dd, rs)
        codes = _codes(vr, "L3")
        assert "N28" in codes, "增量资产单规则（即使带增量段）必须被拦"
        assert "N14" not in codes, "有 incremental 段，N14 不该报"

    def test_two_rule_form_passes_new_checks(self):
        """标准两规则形态（extract→tmp + merge→目标）过 N28/N_INIT2。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        vr = _run(dd, rs)
        codes = _codes(vr, "L3")
        assert "N28" not in codes
        assert "N_INIT2" not in codes

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
        """增量 filter 引用未声明的业务参数（非标准参数）→ N22。

        P_START_DATE/P_END_DATE 是标准参数（incremental 资产自动注入，N22 算已声明），
        故 filter 引用它们合法；这里改 filter 引用一个真正未声明的业务参数触发 N22。
        """
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["rules"][0]["incremental"]["filter"] = "update_time >= '${UNDECLARED_PARAM}'"
        dd["params"] = []
        vr = _run(dd, rs)
        assert "N22" in _codes(vr, "LC")

    def test_incremental_injects_standard_date_params(self):
        """增量资产自动注入 P_START_DATE/P_END_DATE（带 default_value）。"""
        from assemble_ts import build_exec_params
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        params = build_exec_params(dd)
        assert "P_CYCLE_ID" in params                              # 所有资产都有
        assert "P_START_DATE" in params and "P_END_DATE" in params  # 增量资产注入
        assert params["P_START_DATE"]["default_value"] == {"type": "dynamic", "expr": "yesterday_ymd"}
        assert params["P_CYCLE_ID"]["standard"] is True

    def test_full_asset_no_date_params(self):
        """全量资产只注入 P_CYCLE_ID，不注入 P_START_DATE/P_END_DATE。"""
        from assemble_ts import build_exec_params
        params = build_exec_params(make_design_decisions())
        assert "P_CYCLE_ID" in params
        assert "P_START_DATE" not in params
        assert "P_END_DATE" not in params

    def test_business_param_default_required(self):
        """业务参数缺 default_value → N_PARAM_DEFAULT hard。"""
        dd = make_design_decisions()
        dd["params"] = [{"name": "ACCT_PERIOD", "value_type": "string"}]  # 无 default_value
        assert "N_PARAM_DEFAULT" in _codes(_run(dd), "LC")

    def test_standard_param_dup_warn(self):
        """重复声明标准参数 → N_PARAM_DUP warn（不阻断）。"""
        dd = make_design_decisions()
        dd["params"] = [{"name": "P_CYCLE_ID", "value_type": "string", "default_value": "X"}]
        assert "N_PARAM_DUP" in _codes(_run(dd), "LC")


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


    def test_n21_schema_prefix_hint(self):
        """distribution_key 带 schema 前缀 → 报错明确格式问题（去掉前缀即可）。"""
        dd = make_design_decisions()
        dd["tables"] = {"dwb_test_f": {"distribution_key": ["dws.id"]}}
        vr = _run(dd)
        n21 = [i["msg"] for i in vr.items if i["code"] == "N21"]
        assert n21 and "schema 前缀" in n21[0]

    def test_n21_missing_field_lists_fields(self):
        """distribution_key 字段真不存在 → 列本表字段帮对照 + 提示不带 schema。"""
        dd = make_design_decisions()
        dd["tables"] = {"dwb_test_f": {"distribution_key": ["no_such_col"]}}
        vr = _run(dd)
        n21 = [i["msg"] for i in vr.items if i["code"] == "N21"]
        assert n21 and "不在该表字段中" in n21[0] and "不带 schema 前缀" in n21[0]

    def test_audit_type_forced_to_standard(self):
        """mapping 审计字段类型偏离标准（如 numeric）→ ts 强制标准类型 + N_AUDIT_TYPE warn。"""
        from conftest import make_rs_input
        fields = [
            {"source_table": "ods_test_f", "source_column": "id", "source_type": "bigint",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "id", "target_column_cn": "ID", "target_type": "bigint",
             "source_alias": "t", "remark": "主键"},
            {"transform_rule": "赋值", "transform_detail": "'N'", "target_column": "del_flag",
             "target_column_cn": "删除标识", "target_type": "nvarchar2(1)", "remark": "审计字段"},
            {"transform_rule": "赋值", "transform_detail": "'${P_CYCLE_ID}'", "target_column": "crt_cycle_id",
             "target_column_cn": "创建批次", "target_type": "numeric", "remark": "审计字段"},  # ★ 偏离标准
            {"transform_rule": "赋值", "transform_detail": "'${P_CYCLE_ID}'", "target_column": "last_upd_cycle_id",
             "target_column_cn": "更新批次", "target_type": "bigint", "remark": "审计字段"},
            {"transform_rule": "赋值", "transform_detail": "CURRENT_TIMESTAMP", "target_column": "dw_last_update_date",
             "target_column_cn": "更新时间", "target_type": "timestamp(0) without time zone", "remark": "审计字段"},
        ]
        rs = make_rs_input(has_audit=False, fields=fields)
        dd = make_design_decisions()
        # 校验 warn（覆盖透明）
        vr = _run(dd, rs)
        assert "N_AUDIT_TYPE" in _codes(vr, "LC")
        # 组装强制标准类型（numeric → bigint）
        ts, _, _ = do_assemble(rs, dd)
        all_fields = []
        for tbl in ts.get("tables", {}).values():
            all_fields.extend(tbl.get("fields", []))
        crt = next(f for f in all_fields if f.get("target_field") == "crt_cycle_id")
        assert crt["field_type"] == "bigint"


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


# ============================================================
# 初始化管道（init）—— 双管道模型 + load_mode 语义 + 装配器 + LI 校验
# ============================================================

class TestLoadModeHardBlock:
    """N_INIT2：增量目标规则 load_mode 不能是 truncate_table（全删全插 与增量矛盾）。"""

    def test_merge_terminal_truncate_reports(self):
        """merge 终态规则 + truncate_table → N_INIT2 hard（这次的 bug 配置）。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        # 把 merge 终态的 load_mode 改成 truncate_table（bug 配置）
        dd["rules"][-1]["load_mode"] = "truncate_table"
        dd["rules"][-1]["write_condition"] = ""
        vr = _run(dd, rs)
        assert "N_INIT2" in _codes(vr, "L3")
        assert _level_of(vr, "N_INIT2") == "hard"

    def test_single_rule_incremental_with_filter_truncate_reports(self):
        """单规则增量（有 incremental.filter + target）+ truncate → N_INIT2。"""
        rs = make_incremental_rs_input()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "增量直灌", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target", "load_mode": "truncate_table",
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
            "incremental": {"key": "update_time",
                            "filter": "update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'",
                            "init_filter": "1=1"},
        }])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        vr = _run(dd, rs)
        assert "N_INIT2" in _codes(vr, "L3")

    def test_intermediate_tmp_truncate_ok(self):
        """中间 tmp（intermediate）的 truncate_table 合法 → 不触发 N_INIT2。"""
        rs = make_incremental_rs_input()
        dd = make_incremental_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        # extract 规则是 intermediate + truncate_table（tmp 重建）→ 不该触发
        vr = _run(dd, rs)
        assert "N_INIT2" not in _codes(vr, "L3")

    def test_non_incremental_full_truncate_ok(self):
        """非增量 full 规则 + target + truncate → 不触发 N_INIT2（全量表本来就该 truncate）。"""
        rs = make_rs_input()
        dd = make_design_decisions()  # 默认单规则 full+target，无 incremental 段
        vr = _run(dd, rs)
        assert "N_INIT2" not in _codes(vr, "L3")


class TestInitAssembler:
    """build_init_section：explicit 展开（7 不变量 + core_from）/ derive 记录。"""

    def test_no_init_section_no_init_key(self):
        """无 init 段 → ts.json 不含 init key。"""
        rs = make_rs_input()
        dd = make_design_decisions()
        ts, _, _ = do_assemble(rs, dd)
        assert "init" not in ts

    def test_explicit_terminal_invariants(self):
        """explicit 终态：target=增量F表 / load_mode=truncate_table / write_condition空 / field_targets=目标全字段。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        ts, _, _ = do_assemble(rs, dd)
        init = ts["init"]
        assert init["mode"] == "explicit"
        assert init["group_mode"] == "inline"
        init_r = init["rules"]["INIT_R0001"]
        # 7 不变量
        assert init_r["target_table"] == "dws.dwb_test_f"  # = 增量终态 F 表
        assert init_r["load_mode"] == "truncate_table"
        assert init_r["write_condition"] == ""
        assert init_r["target_role"] == "target"
        # field_targets = 增量终态全字段
        inc_terminal_targets = ts["rules"]["R0003"]["field_targets"]
        assert init_r["field_targets"] == inc_terminal_targets
        # joins 保留 designer 写的核心结构
        assert len(init_r["joins"]) == 2

    def test_explicit_core_from_copies_field_logics(self):
        """explicit：designer 没写 field_logics + 有 core_from → 从 core_from 抄。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        ts, _, _ = do_assemble(rs, dd)
        init_r = ts["init"]["rules"]["INIT_R0001"]
        # core_from=R0002，R0002 的 field_logics={"id":"核心加工口径：已确认状态取值"}
        assert init_r["field_logics"] == {"id": "核心加工口径：已确认状态取值"}
        assert init_r["core_from"] == "R0002"

    def test_explicit_designer_field_logics_overrides_core_from(self):
        """explicit：designer 自己写了 field_logics → 覆盖 core_from（不抄）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        dd["init"]["rules"][0]["field_logics"] = {"id": "init 专属口径（全量场景）"}
        ts, _, _ = do_assemble(rs, dd)
        init_r = ts["init"]["rules"]["INIT_R0001"]
        assert init_r["field_logics"] == {"id": "init 专属口径（全量场景）"}

    def test_derive_mode_materializes(self):
        """derive：克隆增量规则产 init.rules 元数据（INIT_ 前缀、core_from 指向源、终态 truncate）。"""
        rs = make_incremental_rs_input()
        dd = make_derive_init_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["params"] = [{"name": "BIZ_DATE_START", "value_type": "date"}, {"name": "BIZ_DATE_END", "value_type": "date"}]
        ts, _, _ = do_assemble(rs, dd)
        init = ts["init"]
        assert init["mode"] == "derive"
        assert init["group_mode"] == "inline"
        # 克隆了增量规则（R0001 extract + R0002 merge → INIT_R0001 + INIT_R0002）
        assert "INIT_R0001" in init["rules"]
        assert "INIT_R0002" in init["rules"]
        # extract 克隆：core_from 指向源、load_mode=truncate（init 全先删全插）、保留 incremental 段
        init_extract = init["rules"]["INIT_R0001"]
        assert init_extract["core_from"] == "R0001"
        assert init_extract["load_mode"] == "truncate_table"
        assert init_extract["incremental"]["filter"]  # 源的 delta filter（slice_ts 告诉 coder 改它）
        assert init_extract["incremental"]["init_filter"] == "1=1"
        # 终态克隆：load_mode=truncate（不是 merge_into）、write_condition 空
        init_term = init["rules"]["INIT_R0002"]
        assert init_term["core_from"] == "R0002"
        assert init_term["load_mode"] == "truncate_table"
        assert init_term["target_role"] == "target"
        assert init_term["write_condition"] == ""

    def test_intermediate_init_rule_truncate(self):
        """explicit 中间 tmp 规则：load_mode 强制 truncate_table（全量重建）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        # 加一条中间 init 规则（复用增量 tmp）
        dd["init"]["rules"].append({
            "rule_code": "INIT_PRE", "target_role": "intermediate",
            "target_table": "dws.tmp_rebuilt", "reads": ["dws.tmp_delta"],
            "field_targets": ["id"],
        })
        ts, _, _ = do_assemble(rs, dd)
        init_pre = ts["init"]["rules"]["INIT_PRE"]
        assert init_pre["load_mode"] == "truncate_table"
        assert init_pre["target_role"] == "intermediate"

    def test_separate_mode_creates_init_task(self):
        """group_mode=separate → build_meta 建 tasks['init']（独立一次性任务）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        dd["init"]["group_mode"] = "separate"
        ts, _, _ = do_assemble(rs, dd)
        tasks = ts["meta"]["schedule"]["tasks"]
        assert "init" in tasks
        assert tasks["init"]["task_name"].endswith("_init")

    def test_inline_mode_no_init_task(self):
        """group_mode=inline → 不建独立 init 任务（init 规则进 f 任务，靠 P_FLAG 选跑）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()  # 默认 inline
        ts, _, _ = do_assemble(rs, dd)
        tasks = ts["meta"]["schedule"]["tasks"]
        assert "init" not in tasks

    def test_inline_mode_injects_p_flag(self):
        """group_mode=inline → exec_params 自动注 P_FLAG（designer 不用声明）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()  # inline
        ts, _, _ = do_assemble(rs, dd)
        exec_params = ts["meta"]["schedule"]["exec_params"]
        assert "P_FLAG" in exec_params

    def test_separate_mode_no_p_flag(self):
        """group_mode=separate → 不注 P_FLAG（独立任务，无需运行时选跑）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        dd["init"]["group_mode"] = "separate"
        ts, _, _ = do_assemble(rs, dd)
        exec_params = ts["meta"]["schedule"]["exec_params"]
        assert "P_FLAG" not in exec_params

    def test_no_init_no_p_flag_no_task(self):
        """无 init 段 → 既无 P_FLAG 也无 init 任务（向后兼容）。"""
        rs = make_rs_input()
        dd = make_design_decisions()
        ts, _, _ = do_assemble(rs, dd)
        assert "init" not in ts
        exec_params = ts["meta"]["schedule"]["exec_params"]
        assert "P_FLAG" not in exec_params
        assert "init" not in ts["meta"]["schedule"]["tasks"]


class TestInitValidation:
    """LI 层 init 校验。"""

    def test_valid_explicit_no_li_hard(self):
        """合法 explicit init → LI 层无 hard。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        vr = _run(dd, rs)
        assert _codes(vr, "LI") == [], f"LI 不该有报错: {_codes(vr, 'LI')}"

    def test_n_init1_explicit_load_mode_hard(self):
        """explicit init 规则显式声明非 truncate 的 load_mode → N_INIT1 hard。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        dd["init"]["rules"][0]["load_mode"] = "merge_into"  # 误填
        vr = _run(dd, rs)
        assert "N_INIT1" in _codes(vr, "LI")
        assert _level_of(vr, "N_INIT1") == "hard"

    def test_n_init3_delta_tmp_warn(self):
        """explicit init 规则读取 delta 机器 tmp → N_INIT3 warn。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        # INIT_R0001 读取 tmp_delta（R0001 incremental_extract 产出的 delta 机器 tmp）
        dd["init"]["rules"][0]["reads"] = ["dws.tmp_delta"]
        vr = _run(dd, rs)
        assert "N_INIT3" in _codes(vr, "LI")
        assert _level_of(vr, "N_INIT3") == "warn"

    def test_n_init4_empty_logics_warn(self):
        """explicit init 规则既无 core_from 又无 field_logics → N_INIT4 warn。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        dd["init"]["rules"][0]["core_from"] = ""  # 清掉 core_from → 无口径来源
        vr = _run(dd, rs)
        assert "N_INIT4" in _codes(vr, "LI")
        assert _level_of(vr, "N_INIT4") == "warn"

    def test_bad_mode_hard(self):
        """init.mode 非法值 → N_INIT_MODE hard。"""
        rs = make_incremental_rs_input()
        dd = make_derive_init_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["init"]["mode"] = "auto"
        vr = _run(dd, rs)
        assert "N_INIT_MODE" in _codes(vr, "LI")
        assert _level_of(vr, "N_INIT_MODE") == "hard"

    def test_bad_group_mode_hard(self):
        """init.group_mode 非法值 → N_INIT_GROUP hard。"""
        rs = make_incremental_rs_input()
        dd = make_derive_init_decisions([{"key": "update_time", "table": "ods_test_f"}])
        dd["init"]["group_mode"] = "mixed"
        vr = _run(dd, rs)
        assert "N_INIT_GROUP" in _codes(vr, "LI")
        assert _level_of(vr, "N_INIT_GROUP") == "hard"


class TestInitMdRendering:
    """ts.md 渲染 init 段。"""

    def test_explicit_init_renders(self):
        """explicit init → ts.md 含初始化设计段 + init 规则。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        ts, _, _ = do_assemble(rs, dd)
        md = render_md(ts)
        assert "初始化设计" in md
        assert "INIT_R0001" in md
        assert "explicit" in md
        assert "truncate_table" in md

    def test_derive_init_renders(self):
        """derive init → ts.md 含初始化设计段 + 派生说明 + init_filter。"""
        rs = make_incremental_rs_input()
        dd = make_derive_init_decisions([{"key": "update_time", "table": "ods_test_f"}])
        ts, _, _ = do_assemble(rs, dd)
        md = render_md(ts)
        assert "初始化设计" in md
        assert "derive" in md
        assert "init_filter" in md or "1=1" in md  # 列出 extract 的 init_filter

    def test_no_init_no_section(self):
        """无 init 段 → ts.md 不含初始化设计段。"""
        rs = make_rs_input()
        dd = make_design_decisions()
        ts, _, _ = do_assemble(rs, dd)
        md = render_md(ts)
        assert "初始化设计" not in md


class TestTwoPipelinesSameTable:
    """增量终态 + init 终态同写 F 表：不冲突，字段集一致。"""

    def test_init_terminal_same_target_as_incremental(self):
        """init 终态 target_table == 增量终态 F 表；tables 里该表只建一次。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        ts, _, _ = do_assemble(rs, dd)
        inc_terminal = ts["rules"]["R0003"]["target_table"]
        init_terminal = ts["init"]["rules"]["INIT_R0001"]["target_table"]
        assert inc_terminal == init_terminal == "dws.dwb_test_f"
        # tables 里 dwb_test_f 只有一份（build_tables 按 tbl_short 去重）
        assert "dwb_test_f" in ts["tables"]

    def test_init_terminal_field_targets_match_target_schema(self):
        """init 终态 field_targets = 增量终态全字段（同一张表同一份 schema）。"""
        rs = make_incremental_rs_input()
        dd = make_explicit_init_decisions()
        ts, _, _ = do_assemble(rs, dd)
        inc_ft = ts["rules"]["R0003"]["field_targets"]
        init_ft = ts["init"]["rules"]["INIT_R0001"]["field_targets"]
        assert set(inc_ft) == set(init_ft)


class TestN29TranslateGuard:
    """N29 warn：design_logic 照抄 mapping 原文（翻译者原则的产物探测）。只查数据加工类。"""

    def _agg_rs(self):
        rs = make_rs_input(fields=[
            {"source_table": "ods_test_f", "source_column": "id", "source_type": "bigint",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "id", "target_column_cn": "ID", "target_type": "bigint",
             "source_alias": "t", "remark": ""},
            {"source_table": "ods_pay_f", "source_column": "no", "source_type": "varchar(50)",
             "transform_rule": "数据加工", "transform_detail": "将同一个t.id对应的m.no值拼接，限制m.del_flag=N，用,隔开",
             "target_column": "pay_nos", "target_column_cn": "付款单号串", "target_type": "varchar(2000)",
             "source_alias": "m", "remark": ""},
        ], has_audit=True)
        return rs

    def test_copied_logic_warns(self):
        """design_logic 与 transform_detail 完全一致 → N29 warn。"""
        rs = self._agg_rs()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["id", "pay_nos", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {"pay_nos": "将同一个t.id对应的m.no值拼接，限制m.del_flag=N，用,隔开"},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        warns = [i for i in vr.items if i["code"] == "N29" and i["level"] == "warn"]
        assert warns, "照抄原文应触发 N29 warn"

    def test_translated_logic_no_warn(self):
        """拆解后的技术口径（与原文不同）→ 无 N29。"""
        rs = self._agg_rs()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["id", "pay_nos", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {"pay_nos": "m 表先按 t.id 预聚合（过滤 del_flag='N'，no 去重，按 no 排序）拼接为逗号分隔串"},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        assert "N29" not in _codes(vr), "翻译过的 design_logic 不该报"

    def test_direct_field_not_checked(self):
        """直取字段（脚本的'直取 t.id'恰好等于 detail 时）不查——只对数据加工类。"""
        rs = self._agg_rs()
        rs["field_mappings"][0]["transform_detail"] = "直取 t.id"
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["id", "pay_nos", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {"pay_nos": "m 表预聚合拼接"},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        assert "N29" not in _codes(vr)


class TestN30JoinFieldExistence:
    """N30：designer 声明的 joins 引用字段必须真实存在（schema_cache 硬校验，无缓存降 warn）。"""

    def _two_src_rs(self):
        rs = make_rs_input(fields=[
            {"source_table": "ods_test_f", "source_column": "id", "source_type": "bigint",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "id", "target_column_cn": "ID", "target_type": "bigint",
             "source_alias": "t", "remark": ""},
        ], has_audit=True)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_test_f", "source_table_cn": "主",
             "source_alias": "t", "join_condition": ""},
            {"source_schema": "ods", "source_table": "ods_pay_f", "source_table_cn": "从",
             "source_alias": "m", "join_condition": "t.id = m.order_id and rn = 1"},
        ]
        return rs

    def _cache(self, tmp_path, extra_pay=None):
        pay = {"order_id": "bigint", "no": "varchar(50)", "del_flag": "varchar(1)"}
        if extra_pay:
            pay.update(extra_pay)
        cache = {"cached_at": "", "tables": {
            "ods.ods_test_f": {"id": "bigint"},
            "ods.ods_pay_f": pay,
        }}
        p = tmp_path / "schema_cache.json"
        p.write_text(json.dumps(cache), encoding="utf-8")
        return p

    def _dd(self, condition):
        return make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "joins": [{"alias": "m", "type": "LEFT JOIN", "condition": condition}],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])

    def _run_with_cache(self, dd, rs, cache_path):
        field_map = {fm["target_column"]: fm for fm in rs["field_mappings"]}
        return run_all_validations(dd, rs, field_map, schema_cache_path=cache_path)

    def test_qualified_missing_field_hard(self, tmp_path):
        """别名限定引用的列在源表不存在 → N30 hard（rn 抄进限定引用的变体）。"""
        rs = self._two_src_rs()
        cache = self._cache(tmp_path)  # ods_pay_f 无 cust_id
        vr = self._run_with_cache(self._dd("t.id = m.cust_id"), rs, cache)
        assert "N30" in _codes(vr, "L4")
        msgs = [i["msg"] for i in vr.items if i["code"] == "N30"]
        assert any("cust_id" in m for m in msgs)

    def test_bare_rn_literal_hard(self, tmp_path):
        """回归核心：'on x=x and rn=1' 的裸 rn 在所有涉及表都不存在 → N30 hard + 开窗残留提示。"""
        rs = self._two_src_rs()
        cache = self._cache(tmp_path)
        vr = self._run_with_cache(self._dd("t.id = m.order_id and rn = 1"), rs, cache)
        assert "N30" in _codes(vr, "L4")
        msgs = [i["msg"] for i in vr.items if i["code"] == "N30"]
        assert any("rn" in m and "开窗" in m for m in msgs), msgs

    def test_existing_bare_literal_ok(self, tmp_path):
        """裸字段确实存在（del_flag='N'）→ 不报。"""
        rs = self._two_src_rs()
        cache = self._cache(tmp_path)
        vr = self._run_with_cache(self._dd("t.id = m.order_id and m.del_flag = 'N'"), rs, cache)
        assert "N30" not in _codes(vr, "L4")

    def test_no_cache_degrades_to_warn(self, tmp_path):
        """无 schema_cache（未连库）→ 降为单条 warn，不硬拦。"""
        rs = self._two_src_rs()
        vr = self._run_with_cache(self._dd("t.id = m.order_id and rn = 1"), rs,
                                  tmp_path / "not_exist.json")
        n30_items = [i for i in vr.items if i["code"] == "N30"]
        assert all(i["level"] == "warn" for i in n30_items), "无缓存应是 warn，不该有 hard"
        assert n30_items, "无缓存应是 warn 提示"

    def test_valid_condition_passes(self, tmp_path):
        """全部引用存在 → 无 N30。"""
        rs = self._two_src_rs()
        cache = self._cache(tmp_path)
        vr = self._run_with_cache(self._dd("t.id = m.order_id"), rs, cache)
        assert "N30" not in _codes(vr, "L4")


class TestAssemblyFieldLineage:
    """装配/merge 规则的无 logic 字段默认=tmp 搬运（不再沿用 step1 源表别名 ht.a）。

    回归：两步设计（step1 多源加工→tmp1，step2 tmp1→merge 目标），step2 字段的
    design_logic/source_fields 曾错指 ht.a（build_field 的 direct 分支先于
    is_assembly 触发），coder 照写 SQL 在 UT 炸。
    """

    def _rs(self, extra_fields=None):
        fields = [
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
            {"source_table": "ods_ht_f", "source_column": "amt", "source_type": "numeric(18,2)",
             "transform_rule": "数据加工", "transform_detail": "金额×汇率",
             "target_column": "amt_cny", "target_column_cn": "本币金额", "target_type": "numeric(18,2)",
             "source_alias": "ht", "remark": ""},
        ]
        if extra_fields:
            fields.extend(extra_fields)
        rs = make_rs_input(fields=fields, has_audit=True)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_ht_f", "source_table_cn": "合同",
             "source_alias": "ht", "join_condition": ""},
        ]
        for ef in (extra_fields or []):
            rs["source_tables"].append({
                "source_schema": ef.get("source_schema", "ods"),
                "source_table": ef["source_table"], "source_table_cn": "",
                "source_alias": ef["source_alias"], "join_condition": ""})
        return rs

    def test_step2_field_carries_from_tmp(self):
        """step2（merge，无 field_logics）：direct 和加工字段都默认 tmp 搬运，不指 ht。"""
        rs = self._rs()
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "加工", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp1",
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["a", "amt_cny", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {"amt_cny": "金额×汇率"},
             "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id",
             "produces_for": [], "reads": ["dws.tmp1"],
             "field_targets": ["a", "amt_cny", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {},
             "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        ts, _, _ = do_assemble(rs, dd)
        f_tbl = ts["tables"]["dwb_test_f"]
        by_name = {f["target_field"]: f for f in f_tbl["fields"]}
        # 直接复制字段（mapping 别名 ht）：搬运默认，指向 tmp1 不是 ht
        f_a = by_name["a"]
        assert f_a["design_logic"].startswith("直取 tmp1.a"), f_a["design_logic"]
        assert "ht" not in f_a["design_logic"]
        assert f_a["source_fields"] == [{"table": "tmp1", "field": "a", "alias": "tmp1"}]  # 字符串 reads 默认别名=表短名
        # 加工字段：同样搬运（前序已加工）
        f_amt = by_name["amt_cny"]
        assert f_amt["design_logic"].startswith("直取 tmp1.amt_cny"), f_amt["design_logic"]
        assert f_amt["source_fields"][0]["table"] == "tmp1"
        assert f_amt["transform_type"] == "direct"

    def test_step2_joined_source_field_keeps_alias(self):
        """case B：step2 另 join 源表 cx 补取字段——cx 字段保持'直取 cx.b'，ht 字段仍搬运。"""
        rs = self._rs(extra_fields=[
            {"source_table": "ods_cx_f", "source_column": "b", "source_type": "varchar(20)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "b", "target_column_cn": "字段B", "target_type": "varchar(20)",
             "source_alias": "cx", "remark": ""},
        ])
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "加工", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp1",
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["a", "amt_cny", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {"amt_cny": "金额×汇率"},
             "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id",
             "produces_for": [], "reads": ["dws.tmp1"],
             "source_aliases": ["cx"],
             "joins": [{"alias": "cx", "type": "LEFT JOIN", "condition": "t1.a = cx.a"}],
             "field_targets": ["a", "amt_cny", "b", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {},
             "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert by_name["b"]["design_logic"] == "直取 cx.b"  # join 进来的真源表
        assert by_name["b"]["source_fields"][0]["alias"] == "cx"
        assert by_name["a"]["design_logic"].startswith("直取 tmp1.a")  # ht 血缘仍搬运

    def test_multi_tmp_lineage_precision(self):
        """模式二：双 tmp（tmp_a/tmp_b），字段血缘精确归属各自的 tmp。"""
        rs = self._rs(extra_fields=[
            {"source_table": "ods_py_f", "source_column": "p", "source_type": "varchar(10)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "p", "target_column_cn": "字段P", "target_type": "varchar(10)",
             "source_alias": "py", "remark": ""},
        ])
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "取A", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp_a",
             "step_type": "full", "target_role": "intermediate",
             "produces_for": ["R0003"], "reads": [],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "无"}},
            {"rule_code": "R0002", "rule_name": "取P", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.tmp_b",
             "step_type": "full", "target_role": "intermediate",
             "produces_for": ["R0003"], "reads": [],
             "field_targets": ["p"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "无"}},
            {"rule_code": "R0003", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 3, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id",
             "produces_for": [], "reads": ["dws.tmp_a", "dws.tmp_b"],
             "field_targets": ["a", "p", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert by_name["a"]["design_logic"].startswith("直取 tmp_a.a"), by_name["a"]["design_logic"]
        assert by_name["p"]["design_logic"].startswith("直取 tmp_b.p"), by_name["p"]["design_logic"]

    def test_explicit_logic_wins(self):
        """designer 显式写了 logic → 原样使用（可用自己的 tmp 别名口径 t1.a）。"""
        rs = self._rs()
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "加工", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp1",
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id",
             "produces_for": [], "reads": ["dws.tmp1"],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {"a": "直取 t1.a（tmp1 别名 t1）"},
             "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert by_name["a"]["design_logic"] == "直取 t1.a（tmp1 别名 t1）"


class TestReadsAliasForm:
    """reads 对象形式 {table, alias}：tmp 别名贯通 design_logic/source_fields/伪源表/source_refs。"""

    def _two_step(self, reads_form):
        rs = make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
        ], has_audit=True)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_ht_f", "source_table_cn": "合同",
             "source_alias": "ht", "join_condition": ""}]
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "加工", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp1",
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id",
             "produces_for": [], "reads": reads_form,
             "joins": [{"alias": "t1", "type": "main"}],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        return rs, dd

    def test_object_form_alias_threaded(self):
        """对象形式 reads：t1 别名贯通（design_logic/source_fields/source_refs），ts.reads 仍表名。"""
        rs, dd = self._two_step([{"table": "dws.tmp1", "alias": "t1"}])
        ts, _, _ = do_assemble(rs, dd)
        r2 = ts["rules"]["R0002"]
        assert r2["reads"] == ["dws.tmp1"]  # DAG 语义不变
        pseudo = [s for s in r2["source_tables"] if s.get("_from_reads")]
        assert pseudo and pseudo[0]["alias"] == "t1"
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert by_name["a"]["design_logic"].startswith("直取 t1.a"), by_name["a"]["design_logic"]
        assert by_name["a"]["source_fields"] == [{"table": "tmp1", "field": "a", "alias": "t1"}]
        assert r2["source_refs"]["a"] == "t1.a"

    def test_string_form_default_alias(self):
        """字符串形式 reads：别名默认=表短名（向后兼容）。"""
        rs, dd = self._two_step(["dws.tmp1"])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert by_name["a"]["design_logic"].startswith("直取 tmp1.a")
        assert ts["rules"]["R0002"]["source_refs"]["a"] == "tmp1.a"


class TestAliasBindingValidation:
    """N31（别名一规则一表硬拦）/ N32（无绑定别名 warn）。"""

    def _rs(self):
        rs = make_rs_input(has_audit=True)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_ht_f", "source_table_cn": "合同",
             "source_alias": "ht", "join_condition": ""}]
        return rs

    def test_n31_alias_bound_to_two_tables(self):
        """tmp 别名撞 rs_input 源表别名（本规则引用了 ht）→ N31 hard。"""
        rs = self._rs()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "合并", "scenario": "default",
            "exec_sequence": 2, "target_table": "dws.dwb_test_f",
            "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
            "write_condition": "T.id=T1.id",
            "source_aliases": ["ht"], "reads": [{"table": "dws.tmp1", "alias": "ht"}],
            "joins": [{"alias": "ht", "type": "main"}],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        assert "N31" in _codes(vr, "L4")

    def test_n31_not_fired_when_alias_unused_in_rule(self):
        """rs_input 有别名 ht 但本规则没引用，tmp 复用该名不冲突（规则内唯一即可）。"""
        rs = self._rs()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "合并", "scenario": "default",
            "exec_sequence": 2, "target_table": "dws.dwb_test_f",
            "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
            "write_condition": "T.id=T1.id",
            "source_aliases": [], "reads": [{"table": "dws.tmp1", "alias": "ht"}],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        assert "N31" not in _codes(vr, "L4")

    def test_n32_unbound_join_alias_warns(self):
        """joins 引用的别名既不在 rs_input 也不在 reads → N32 warn（提示 reads 对象声明）。"""
        rs = self._rs()
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "joins": [{"alias": "t9", "type": "LEFT JOIN", "condition": "t9.a = ht.a"}],
            "source_aliases": ["ht"],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        warns = [i for i in vr.items if i["code"] == "N32" and i["level"] == "warn"]
        assert warns and "t9" in warns[0]["msg"]


class TestAccumulateFieldUnion:
    """accumulate 多规则写同表：字段并集入表（修首规则整表跳过丢字段 bug）+ source_refs 各归各。"""

    def test_union_and_per_rule_refs(self):
        rs = make_rs_input(fields=[
            {"source_table": "ods_a_f", "source_column": "x", "source_type": "varchar(10)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "x", "target_column_cn": "X", "target_type": "varchar(10)",
             "source_alias": "ta", "remark": ""},
            {"source_table": "ods_b_f", "source_column": "y", "source_type": "varchar(10)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "y", "target_column_cn": "Y", "target_type": "varchar(10)",
             "source_alias": "tb", "remark": ""},
        ], has_audit=False)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_a_f", "source_table_cn": "A",
             "source_alias": "ta", "join_condition": ""},
            {"source_schema": "ods", "source_table": "ods_b_f", "source_table_cn": "B",
             "source_alias": "tb", "join_condition": ""},
        ]
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "来源A", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.tmp_c",
             "step_type": "full", "target_role": "intermediate",
             "produces_for": ["R0003"], "reads": [], "source_aliases": ["ta"],
             "field_targets": ["x"], "field_logics": {},
             "grain": {"input": "源", "output": "中间", "change": "无"}},
            {"rule_code": "R0002", "rule_name": "来源B", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.tmp_c",
             "step_type": "full", "target_role": "intermediate",
             "produces_for": ["R0003"], "reads": [], "source_aliases": ["tb"],
             "field_targets": ["y"], "field_logics": {},
             "grain": {"input": "源", "output": "中间", "change": "无"}},
        ])
        dd.setdefault("tables", {})["tmp_c"] = {"build_mode": "accumulate"}
        ts, _, _ = do_assemble(rs, dd)
        field_names = {f["target_field"] for f in ts["tables"]["tmp_c"]["fields"]}
        assert {"x", "y"} <= field_names, f"accumulate 并集丢字段: {field_names}"
        assert ts["rules"]["R0001"]["source_refs"]["x"] == "ta.x"
        assert ts["rules"]["R0002"]["source_refs"]["y"] == "tb.y"


class TestTmpNaming:
    """N33：tmp 命名规范 warn（目标表主体+_tmp+序号；特殊命名 warn 不拦）。"""

    def _dd(self, tmp_table):
        return make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "取数", "scenario": "default",
             "exec_sequence": 1, "target_table": tmp_table,
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id", "produces_for": [], "reads": [tmp_table],
             "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])

    def test_standard_name_no_warn(self):
        rs = make_rs_input()
        vr = _run(self._dd("dws.dwb_test_tmp1"), rs)
        assert "N33" not in _codes(vr, "L2")

    def test_tmp_prefix_name_warns(self):
        """tmp 前置（tmp_x）→ warn 提示规范。"""
        rs = make_rs_input()
        vr = _run(self._dd("dws.tmp_order"), rs)
        warns = [i for i in vr.items if i["code"] == "N33" and i["level"] == "warn"]
        assert warns and "tmp_order" in warns[0]["msg"]


class TestAssignCarryInAssembly:
    """装配规则赋值字段也 tmp 搬运（赋值动作只在产出规则发生一次）。

    回归：两步设计（R1 加工+赋值→tmp1，R2 merge），R2 的赋值字段曾被 assign
    分支拦下烘焙"固定赋值"（或错标输入的加工原文），不从 tmp 搬运。
    """

    def test_audit_assign_carried_from_tmp(self):
        rs = make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
        ], has_audit=True)  # 审计字段=赋值类（del_flag 'N' 等）
        dd = make_design_decisions(rules=[
            {"rule_code": "R0001", "rule_name": "加工", "scenario": "default",
             "exec_sequence": 1, "target_table": "dws.dwb_test_tmp1",
             "step_type": "aggregate", "target_role": "intermediate",
             "produces_for": ["R0002"], "reads": [],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "源", "output": "中间", "change": "聚合"}},
            {"rule_code": "R0002", "rule_name": "合并", "scenario": "default",
             "exec_sequence": 2, "target_table": "dws.dwb_test_f",
             "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
             "write_condition": "T.id=T1.id", "produces_for": [], "reads": ["dws.dwb_test_tmp1"],
             "field_targets": ["a", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
             "field_logics": {}, "grain": {"input": "中间", "output": "目标", "change": "无"}},
        ])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        # 赋值类审计字段在 R2 = tmp 搬运，不再"固定赋值"
        f_del = by_name["del_flag"]
        assert f_del["design_logic"].startswith("直取 dwb_test_tmp1.del_flag"), f_del["design_logic"]
        assert f_del["transform_type"] == "direct"
        assert f_del["source_fields"][0]["table"] == "dwb_test_tmp1"
        assert ts["rules"]["R0002"]["source_refs"]["del_flag"] == "dwb_test_tmp1.del_flag"
        # R1（产出规则）里仍是赋值语义（fixed）——赋值只发生一次
        r1_by = {f["target_field"]: f for f in ts["tables"]["dwb_test_tmp1"]["fields"]}
        assert r1_by["del_flag"]["design_logic"] == "固定赋值 'N'"

    def test_mislabeled_assign_falls_back_to_processing(self):
        """兜底：错标赋值实为加工（手工 rs_input 绕过 N35 校验）→ detail 当口径底稿。"""
        rs = make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
            {"source_table": "ods_ht_f", "source_column": "", "source_type": "",
             "transform_rule": "赋值", "transform_detail": "CASE WHEN a=1 THEN 'Y' ELSE 'N' END",
             "target_column": "flag", "target_column_cn": "标记", "target_type": "varchar(1)",
             "source_alias": "ht", "remark": ""},
        ], has_audit=False)
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["a", "flag"],
            "field_logics": {"flag": "CASE WHEN ht.a=1 THEN 'Y' ELSE 'N' END"},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        ts, _, _ = do_assemble(rs, dd)
        by_name = {f["target_field"]: f for f in ts["tables"]["dwb_test_f"]["fields"]}
        assert "CASE WHEN" in by_name["flag"]["design_logic"]  # 真实口径，不是"固定赋值"

    def test_orphan_field_logics_warns(self):
        """N34：logic 写了但字段不在 targets → warn（防静默丢弃）。"""
        rs = make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "数据加工", "transform_detail": "x 加工",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
            {"source_table": "ods_ht_f", "source_column": "b", "source_type": "varchar(50)",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "b", "target_column_cn": "字段B", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
        ], has_audit=False)
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["a", "b"],
            "field_logics": {"a": "口径A", "ghost": "写给不存在归属的字段的口径"},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        vr = _run(dd, rs)
        warns = [i for i in vr.items if i["code"] == "N34" and i["level"] == "warn"]
        assert warns and "ghost" in warns[0]["msg"], warns

    def test_n30_checks_design_logic_refs(self, tmp_path):
        """N30 扩展：design_logic 里的 别名.字段 限定引用也查存在性（SCD2 start_date 假设）。"""
        import json as _json
        rs = make_rs_input(fields=[
            {"source_table": "ods_ht_f", "source_column": "a", "source_type": "varchar(50)",
             "transform_rule": "数据加工", "transform_detail": "取最新",
             "target_column": "a", "target_column_cn": "字段A", "target_type": "varchar(50)",
             "source_alias": "ht", "remark": ""},
        ], has_audit=False)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_ht_f", "source_table_cn": "合同",
             "source_alias": "ht", "join_condition": ""}]
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "单规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "field_targets": ["a"],
            "field_logics": {"a": "按 ht.start_date 排序取最新一条"},  # ★ 惯例假设的字段
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        cache = {"cached_at": "", "tables": {"ods.ods_ht_f": {"a": "varchar(50)"}}}  # 无 start_date
        cp = tmp_path / "schema_cache.json"
        cp.write_text(_json.dumps(cache), encoding="utf-8")
        field_map = {fm["target_column"]: fm for fm in rs["field_mappings"]}
        vr = run_all_validations(dd, rs, field_map, schema_cache_path=cp)
        n30 = [i for i in vr.items if i["code"] == "N30" and i["level"] == "hard"]
        assert any("start_date" in i["msg"] for i in n30), [i["msg"] for i in n30]


class TestCheckField:
    """designer 自有字段查证入口：别名解析/相似建议/全表/未知别名。"""

    def _setup(self, tmp_path):
        import json as _json
        d = tmp_path / "_internal"
        d.mkdir(exist_ok=True)
        (d / "rs_input.json").write_text(_json.dumps({
            "source_tables": [
                {"source_schema": "ods", "source_table": "ods_emp_f", "source_alias": "emp"}],
            "field_mappings": []}), encoding="utf-8")
        (d / "schema_cache.json").write_text(_json.dumps({
            "tables": {"ods.ods_emp_f": {"emp_id": "bigint", "start_dt": "date", "eff_date": "date"}}}),
            encoding="utf-8")
        return d / "rs_input.json"

    def test_exists(self, tmp_path):
        from check_field import check_field
        out = check_field(self._setup(tmp_path), "emp.start_dt")
        assert "✓" in out and "date" in out

    def test_missing_with_suggestion(self, tmp_path):
        from check_field import check_field
        out = check_field(self._setup(tmp_path), "emp.start_date")
        assert "✗" in out and "start_dt" in out  # 相似建议命中

    def test_alias_only_lists_table(self, tmp_path):
        from check_field import check_field
        out = check_field(self._setup(tmp_path), "emp")
        assert "emp_id" in out and "eff_date" in out

    def test_unknown_alias(self, tmp_path):
        from check_field import check_field
        out = check_field(self._setup(tmp_path), "xx.yy")
        assert "别名未识别" in out and "emp" in out

    def test_n30_join_filter_checked(self, tmp_path):
        """N30 覆盖 join_safety.join_filter 的字段引用。"""
        import json as _json
        rs = make_rs_input(has_audit=True)
        rs["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_ht_f", "source_table_cn": "合同",
             "source_alias": "ht", "join_condition": ""}]
        dd = make_design_decisions(rules=[{
            "rule_code": "R0001", "rule_name": "装配", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f",
            "step_type": "full", "target_role": "target",
            "joins": [{"alias": "ht", "type": "LEFT JOIN", "condition": "ht.id = ht.id"}],
            "join_safety": [{"table": "ods_ht_f", "join_filter": "ht.is_current = 1",
                             "join_key_unique": True, "strategy": "", "reason": ""}],
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {}, "grain": {"input": "源", "output": "目标", "change": "无"},
        }])
        cp = tmp_path / "schema_cache.json"
        cp.write_text(_json.dumps({"tables": {"ods.ods_ht_f": {"id": "bigint"}}}), encoding="utf-8")
        field_map = {fm["target_column"]: fm for fm in rs["field_mappings"]}
        vr = run_all_validations(dd, rs, field_map, schema_cache_path=cp, rs_path=cp.parent / "rs_input.json")
        n30 = [i for i in vr.items if i["code"] == "N30" and "is_current" in i["msg"]]
        assert n30 and "check_field" in n30[0]["msg"]  # 拦截 + 教学命令
