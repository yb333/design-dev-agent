"""assemble_ts.py 的 build_rule 测试。

重点覆盖 source_tables 的"留空兜底"行为：
designer 在 design_decisions 里把 source_aliases 留空（或省略）时，
脚本应默认用 rs_input 的所有 source_tables 补全（见 design_decisions 模板注释）。

回归背景：build_rule 原先只在 source_aliases 非空时填 source_tables，
留空时产出 []，导致 check_sql 报"SELECT 引用了不在 ts.json source_tables 里的表"。
"""

import json
import pytest

from assemble_ts import build_rule


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
        }, {}, _rs_sources())
        assert rule["step_type"] == "aggregate"
        assert rule["target_role"] == "intermediate"
        assert rule["produces_for"] == ["R0003"]
        assert rule["reads"] == []

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
        """有 schedule_config 时，tasks.f/view/dq 都有 project_name/task_group。"""
        sched_cfg = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"},
            "dq_override": {"project_name": "SRP_DQ", "task_group": "GROUP_DQ"},
        }
        monkeypatch.setattr("assemble_ts.load_schedule_config", lambda: sched_cfg)
        meta = build_meta(_rs_input_for_meta(), {"schedule": {"cron": "0 30 3 * * ?"}})
        tasks = meta["schedule"]["tasks"]
        assert tasks["f"]["project_name"] == "SRP_DAILY"
        assert tasks["f"]["task_group"] == "GROUP_SPRD"
        assert tasks["view"]["project_name"] == "SRP_DAILY"
        # dq 走 dq_override
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
        }}
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
