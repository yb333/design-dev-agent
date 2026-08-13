"""平台制品包 exporter 测试。

覆盖：
- platform_config 加载 + 兜底
- execution_tasks.xlsx（RULE/GroupVariables/TargetFields/空sheet）
- schedule_tasks.xlsx（tasks/jobs/taskParams）
- export_manifest.json
- 编码全部留空（关键约束）
"""
import json
from pathlib import Path

import pytest
import openpyxl

# conftest 已把 coding scripts 加入 sys.path
from assemble_export import (
    load_platform_config,
    resolve_config_by_schema,
    build_rule_rows,
    build_group_variables,
    build_target_fields,
    generate_execution_excel,
    generate_schedule_excel,
    generate_manifest,
    AUDIT_FIELDS,
    RULE_COLUMNS,
    GROUPVARS_COLUMNS,
    TARGETFIELDS_COLUMNS,
    TASKS_COLUMNS,
    JOBS_COLUMNS,
    TASKPARAMS_COLUMNS,
    _RULE_COL,
    _cfg,
    _split_schema_table,
)


# ============================================================
# 测试用 ts.json fixture
# ============================================================

@pytest.fixture
def sample_ts():
    """单规则 + 视图的测试数据"""
    return {
        "meta": {
            "target": {
                "f_table": {"schema": "dws", "table": "dwb_xxx_f", "cn": "XXX宽表"},
                "i_view": {"schema": "dws", "table": "dwb_xxx_i", "cn": "XXX宽表"},
            },
            "schedule": {
                "schedule_type": "daily",
                "cron": "0 30 3 * * ?",
                "exec_params": {"P_CYCLE_ID": {"value_type": "string", "desc": "批次号", "standard": True}},
                "lts_params": [
                    {"lts_var": "V_CYCLE_ID", "etl_param": "P_CYCLE_ID", "desc": "批次号"},
                    {"lts_var": "V_GROUP_CODE", "etl_param": "", "desc": "规则组编码"},
                ],
                "tasks": {
                    "f": {
                        "task_name": "task_dwb_xxx_f",
                        "job_name": "Pjob_dwb_xxx_f",
                        "cron": "0 30 3 * * ?",
                        "upstream": [
                            {"table": "ods_order_f", "task": "task_ods_order_f", "dep_type": "宽依赖"},
                            {"table": "dim_product_f", "task": "task_dim_product_f", "dep_type": "宽依赖"},
                        ],
                    },
                    "view": {
                        "task_name": "task_dwb_xxx_i",
                        "job_name": "Pjob_dwb_xxx_i",
                        "cron": "0 30 3 * * ?",
                        "upstream": [{"table": "dwb_xxx_f", "task": "task_dwb_xxx_f", "dep_type": "宽依赖"}],
                    },
                    "dq": {
                        "task_name": "task_dwb_xxx_f_dq",
                        "job_name": "Pjob_dwb_xxx_f_dq",
                        "cron": "0 30 3 * * ?",
                        "upstream": [{"table": "dwb_xxx_i", "task": "task_dwb_xxx_i", "dep_type": "宽依赖"}],
                    },
                },
            },
        },
        "rules": {
            "R0001": {
                "rule_name": "XXX汇总",
                "target_table": "dwb_xxx_f",
                "exec_sequence": 1,
                "is_view_step": False,
                "source_tables": [{"schema": "ods", "table": "ods_order_f", "alias": "a"}],
                "fields": [
                    {"target_field": "order_id", "source_fields": [{"table": "ods_order_f", "field": "order_id", "alias": "a"}]},
                    {"target_field": "order_amt", "source_fields": [{"table": "ods_order_f", "field": "amount", "alias": "a"}]},
                    {"target_field": "del_flag", "source_fields": []},       # 审计字段
                    {"target_field": "crt_cycle_id", "source_fields": []},   # 审计字段
                ],
            },
        },
    }


@pytest.fixture
def sample_config():
    """resolve_config_by_schema 返回的结构"""
    return {
        "shujia": {
            "project_code": "SRP_ETL",
            "project_cn": "ETL项目",
            "project_en": "ETL_Project",
            "datasource": "SRP_DWS",
            "business_owner": "zhangsan",
        },
        "lts": {
            "project_name": "SRP_DAILY",
            "task_group": "GROUP_SPRD",
        },
    }


@pytest.fixture
def etl_dir(tmp_path, sample_ts):
    """造一个 ETL SQL 文件"""
    d = tmp_path / "etl"
    d.mkdir()
    (d / "R0001.sql").write_text("SELECT 1 AS order_id, 100 AS order_amt", encoding="utf-8")
    return d


@pytest.fixture
def ddl_dir(tmp_path):
    """造一个视图 DDL 文件"""
    d = tmp_path / "ddl"
    d.mkdir()
    (d / "create_view_dwb_xxx_i.sql").write_text(
        "CREATE OR REPLACE VIEW dws.dwb_xxx_i AS SELECT * FROM dws.dwb_xxx_f;", encoding="utf-8"
    )
    return d


# ============================================================
# 配置加载
# ============================================================

class TestLoadPlatformConfig:

    def test_load_config(self, tmp_path):
        cfg_file = tmp_path / "platform_config.json"
        cfg_file.write_text(json.dumps({
            "default": {"shujia": {"project_code": "XXX"}, "lts": {"project_name": "P"}},
        }), encoding="utf-8")
        result = load_platform_config(str(cfg_file))
        assert result["default"]["shujia"]["project_code"] == "XXX"

    def test_missing_file_returns_empty(self):
        assert load_platform_config("/nonexistent/path.json") == {}

    def test_cfg_fallback(self):
        """缺失字段用兜底值"""
        assert _cfg({}, "project_code", "FALLBACK") == "FALLBACK"
        assert _cfg({"project_code": ""}, "project_code", "FALLBACK") == "FALLBACK"
        assert _cfg({"project_code": "SRP"}, "project_code", "FALLBACK") == "SRP"


class TestResolveConfigBySchema:

    def test_schema_mapping_hit(self):
        """schema 在 mappings 里有 → 用 schema 的配置"""
        raw = {
            "default": {"shujia": {"project_code": "DEFAULT"}, "lts": {"project_name": "DEF"}},
            "schema_mappings": {
                "slprd": {"shujia": {"project_code": "SLPRD"}, "lts": {"project_name": "SLPRD_DAILY"}},
            },
        }
        result = resolve_config_by_schema(raw, "slprd")
        assert result["shujia"]["project_code"] == "SLPRD"
        assert result["lts"]["project_name"] == "SLPRD_DAILY"

    def test_schema_miss_use_default(self):
        """schema 在 mappings 里没有 → 用 default"""
        raw = {
            "default": {"shujia": {"project_code": "DEFAULT"}, "lts": {"project_name": "DEF"}},
            "schema_mappings": {},
        }
        result = resolve_config_by_schema(raw, "unknown_schema")
        assert result["shujia"]["project_code"] == "DEFAULT"

    def test_partial_override(self):
        """schema 只配了部分字段，其余用 default 兜底"""
        raw = {
            "default": {"shujia": {"project_code": "DEFAULT", "datasource": "DWS"}, "lts": {"project_name": "DEF"}},
            "schema_mappings": {
                "slprd": {"shujia": {"project_code": "SLPRD"}},  # 只覆盖 project_code
            },
        }
        result = resolve_config_by_schema(raw, "slprd")
        assert result["shujia"]["project_code"] == "SLPRD"
        assert result["shujia"]["datasource"] == "DWS"  # default 兜底

    def test_empty_config(self):
        """空配置返回空结构"""
        result = resolve_config_by_schema({}, "slprd")
        assert result == {"shujia": {}, "lts": {}}


# ============================================================
# RULE sheet
# ============================================================

class TestBuildRuleRows:

    def test_rule_row_count(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """RULE 行数 = 取数规则 + 视图规则 + 参数变量"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        # 1 取数 + 1 视图 + 1 参数变量 = 3
        assert len(rows) == 3

    def test_no_view_one_less_row(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """无视图时少一行"""
        sample_ts["meta"]["target"]["i_view"] = {"schema": "", "table": ""}
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        # 1 取数 + 0 视图 + 1 参数变量 = 2
        assert len(rows) == 2

    def test_codes_left_empty(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """规则组编码和规则编码留空（关键约束）"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        for row in rows:
            assert row[_RULE_COL["规则组编码"]] == ""
            assert row[_RULE_COL["规则编码"]] == ""

    def test_etl_query_in_statement(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """取数规则的查询语句列含 SQL 内容"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        etl_row = rows[0]
        assert "SELECT 1 AS order_id" in etl_row[_RULE_COL["(生成的）查询语句1"]]

    def test_view_ddl_in_statement(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """视图规则的查询语句列含 DDL"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        view_row = rows[1]
        assert "CREATE OR REPLACE VIEW" in view_row[_RULE_COL["(生成的）查询语句1"]]

    def test_param_rule_is_type_12(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """参数变量规则类型=12"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        pv_row = rows[-1]
        assert pv_row[_RULE_COL["规则类型"]] == "12"
        assert pv_row[_RULE_COL["规则中文名称"]] == "参数变量规则"

    def test_constants_filled(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """固定常量正确"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        etl_row = rows[0]
        assert etl_row[_RULE_COL["数据库类型"]] == "GaussDB"
        assert etl_row[_RULE_COL["删除模式"]] == "1"
        assert etl_row[_RULE_COL["调度类型"]] == "0"

    def test_column_count_is_82(self, sample_ts, sample_config, etl_dir, ddl_dir):
        """RULE 每行 82 列"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, ddl_dir)
        for row in rows:
            assert len(row) == 82


# ============================================================
# GroupVariables
# ============================================================

class TestBuildGroupVariables:

    def test_vars_from_exec_params(self, sample_ts):
        """参数从 exec_params 来"""
        rows = build_group_variables(sample_ts)
        var_names = [r[1] for r in rows]
        assert "P_CYCLE_ID" in var_names

    def test_default_value_from_ts(self):
        """参数默认值从 ts.default_value 读：static 给值，dynamic 留空（平台注入）。"""
        ts = {"meta": {"schedule": {"exec_params": {
            "P_CYCLE_ID": {"default_value": {"type": "dynamic", "expr": "today_ymdhms"}},
            "BIZ_CODE": {"default_value": "STATIC1"},
        }}}}
        rows = build_group_variables(ts)
        vals = {row[1]: row[5] for row in rows}
        assert vals["P_CYCLE_ID"] == ""       # dynamic → 空，平台运行时注入
        assert vals["BIZ_CODE"] == "STATIC1"  # static 裸串 → 给值

    def test_rule_code_empty(self, sample_ts):
        """规则编码留空"""
        rows = build_group_variables(sample_ts)
        for row in rows:
            assert row[0] == ""

    def test_no_params_empty_rows(self):
        """无 exec_params → 空列表"""
        ts = {"meta": {"schedule": {"exec_params": {}}}}
        assert build_group_variables(ts) == []


# ============================================================
# TargetFields
# ============================================================

class TestBuildTargetFields:

    def test_filter_audit_fields(self, sample_ts):
        """审计字段被过滤"""
        rows = build_target_fields(sample_ts)
        target_fields = [r[1] for r in rows]
        assert "order_id" in target_fields
        assert "del_flag" not in target_fields
        assert "crt_cycle_id" not in target_fields

    def test_source_field_extracted(self, sample_ts):
        """来源字段正确提取，别名不填"""
        rows = build_target_fields(sample_ts)
        for row in rows:
            if row[1] == "order_amt":
                assert row[2] == "amount"
                assert row[5] == ""  # 别名不填

    def test_rule_code_empty(self, sample_ts):
        """规则编码留空"""
        rows = build_target_fields(sample_ts)
        for row in rows:
            assert row[0] == ""


# ============================================================
# Excel 生成（端到端）
# ============================================================

class TestGenerateExecutionExcel:

    def test_10_sheets(self, sample_ts, sample_config, etl_dir, ddl_dir, tmp_path):
        """execution Excel 有 10 个 sheet"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, ddl_dir, out)
        wb = openpyxl.load_workbook(out)
        assert len(wb.sheetnames) == 10
        assert "RULE" in wb.sheetnames
        assert "GroupVariables" in wb.sheetnames
        assert "TargetFields" in wb.sheetnames

    def test_empty_sheets_have_headers_only(self, sample_ts, sample_config, etl_dir, ddl_dir, tmp_path):
        """空 sheet 只有表头"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, ddl_dir, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["ModelRelations"]
        assert ws.max_row == 1  # 只有表头行

    def test_rule_sheet_has_data(self, sample_ts, sample_config, etl_dir, ddl_dir, tmp_path):
        """RULE sheet 有数据行"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, ddl_dir, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["RULE"]
        assert ws.max_row == 4  # 表头 + 3 数据行


class TestGenerateScheduleExcel:

    def test_3_sheets(self, sample_ts, sample_config, tmp_path):
        """schedule Excel 有 3 个 sheet"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        assert wb.sheetnames == ["tasks", "jobs", "taskParams"]

    def test_tasks_has_f_view_dq(self, sample_ts, sample_config, tmp_path):
        """tasks 有 F 表 + 视图 + DQ 三行"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["tasks"]
        assert ws.max_row == 4  # 表头 + F + 视图 + DQ

    def test_jobs_has_upstream_deps(self, sample_ts, sample_config, tmp_path):
        """jobs 含 upstream 依赖行 + view/dq 执行行和依赖"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["jobs"]
        # 表头 + F执行 + 2依赖 + view执行 + view依赖 + dq执行 + dq依赖 = 8
        assert ws.max_row == 8

    def test_cross_project_upstream_uses_dep_project(self, sample_ts, sample_config, tmp_path):
        """跨项目上游依赖：jobs 依赖行的 project/group 用 upstream 项的（不是当前表的）。"""
        # 构造一个跨项目的上游依赖
        ts_cross = json.loads(json.dumps(sample_ts))  # 深拷贝
        ts_cross["meta"]["schedule"]["tasks"]["f"]["upstream"] = [{
            "table": "ods_cross_f",
            "task": "task_ods_cross_f",
            "dep_type": "宽依赖",
            "project": "CROSS_PROJECT",  # 上游在别的项目
            "group": "CROSS_GROUP",
            "app": "CROSS_APP",
        }]
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts_cross, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["jobs"]
        # 找依赖行（job类型=tskdep 的那行）
        header = [c.value for c in ws[1]]
        proj_idx = header.index("项目名称")
        group_idx = header.index("任务组名称")
        jobtype_idx = header.index("job类型")
        dep_rows = [row for row in ws.iter_rows(min_row=2, values_only=True)
                    if row[jobtype_idx] == "tskdep"]
        assert dep_rows, "应有依赖行"
        # 依赖行的 project/group 应是上游的 CROSS_PROJECT/CROSS_GROUP
        assert dep_rows[0][proj_idx] == "CROSS_PROJECT", \
            f"跨项目依赖应用上游project，实际={dep_rows[0][proj_idx]}"
        assert dep_rows[0][group_idx] == "CROSS_GROUP", \
            f"跨项目依赖应用上游group，实际={dep_rows[0][group_idx]}"

    def test_same_project_upstream_fallback_current(self, sample_ts, sample_config, tmp_path):
        """同项目上游（upstream 没配 project/group）→ 用当前表的（兜底）。"""
        # sample_ts 的 upstream 没有 project/group → 应兜底用当前表的 SRP_DAILY/GROUP_SPRD
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["jobs"]
        header = [c.value for c in ws[1]]
        proj_idx = header.index("项目名称")
        jobtype_idx = header.index("job类型")
        dep_rows = [row for row in ws.iter_rows(min_row=2, values_only=True)
                    if row[jobtype_idx] == "tskdep"]
        assert dep_rows
        # 兜底用当前表的配置
        assert dep_rows[0][proj_idx] == "SRP_DAILY", \
            f"同项目应兜底用当前表project，实际={dep_rows[0][proj_idx]}"

    def test_appid_injected_from_config(self, sample_ts, sample_config, tmp_path, monkeypatch):
        """appid 从 schema_apps.json（resolve_appid 按 schema 查）注入到 job 参数。"""
        # appid 不再从 platform_config 的 lts.appid 读——改从 schema_apps（resolve_appid）
        monkeypatch.setattr("assemble_export.resolve_appid", lambda schema, config_path="": "MY_APP_123")
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["jobs"]
        header = [c.value for c in ws[1]]
        params_idx = header.index("job参数")
        exec_rows = [row for row in ws.iter_rows(min_row=2, values_only=True)
                     if row[header.index("job类型")] == "url" and row[header.index("job的父节点名称")] == "start"]
        assert exec_rows, "应有执行行"
        assert "MY_APP_123" in str(exec_rows[0][params_idx]), "appid 应注入 job参数"

    def test_taskparams_v_group_code_empty(self, sample_ts, sample_config, tmp_path):
        """V_GROUP_CODE 值留空"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["taskParams"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            param_name = row[3]
            param_value = row[4]
            if param_name == "V_GROUP_CODE":
                assert param_value == "" or param_value is None

    def test_project_group_from_ts_json(self, sample_config, tmp_path):
        """★ 任务四：ts.json 的 task 有 project_name/task_group 时，exporter 直接用（不走 platform_config）。"""
        # 构造 ts，每个 task 带 project_name/task_group（设计阶段确定的）
        ts = {
            "meta": {
                "target": {"f_table": {"schema": "dws", "table": "dwb_test_f"},
                           "i_view": {"schema": "dws", "table": "dwb_test_i"}},
                "schedule": {
                    "cron": "0 30 3 * * ?",
                    "tasks": {
                        "f": {"task_name": "task_dwb_test_f", "job_name": "Pjob_dwb_test_f",
                              "cron": "0 30 3 * * ?", "upstream": [],
                              "project_name": "TS_PROJ_F", "task_group": "TS_GRP_F"},
                        "view": {"task_name": "task_dwb_test_i", "job_name": "Pjob_dwb_test_i",
                                 "cron": "0 30 3 * * ?", "upstream": [],
                                 "project_name": "TS_PROJ_V", "task_group": "TS_GRP_V"},
                        "dq": {"task_name": "task_dwb_test_f_dq", "job_name": "Pjob_dwb_test_f_dq",
                               "cron": "0 30 3 * * ?", "upstream": [],
                               "project_name": "TS_PROJ_DQ", "task_group": "TS_GRP_DQ"},
                    },
                },
            },
            "rules": {},
        }
        # platform_config 的 lts 配的是另一套（验证不被用）
        cfg = {"lts": {"project_name": "PC_PROJ", "task_group": "PC_GRP", "appid": ""},
               "shujia": {}}
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, cfg, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["tasks"]
        header = [c.value for c in ws[1]]
        proj_idx = header.index("项目名称")
        group_idx = header.index("任务组名称")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        # F 行用 ts.json 的 TS_PROJ_F
        assert rows[0][proj_idx] == "TS_PROJ_F"
        assert rows[0][group_idx] == "TS_GRP_F"
        # view 行用 TS_PROJ_V
        assert rows[1][proj_idx] == "TS_PROJ_V"
        # dq 行用 TS_PROJ_DQ
        assert rows[2][proj_idx] == "TS_PROJ_DQ"

    def test_project_group_fallback_to_platform_config(self, sample_config, tmp_path):
        """★ 任务四兼容：旧 ts.json 没有 project/task_group -> fallback 到 platform_config 的 lts。"""
        ts = {
            "meta": {
                "target": {"f_table": {"schema": "dws", "table": "dwb_test_f"},
                           "i_view": {"schema": "dws", "table": "dwb_test_i"}},
                "schedule": {
                    "cron": "0 30 3 * * ?",
                    "tasks": {
                        "f": {"task_name": "task_dwb_test_f", "job_name": "Pjob_dwb_test_f",
                              "cron": "0 30 3 * * ?", "upstream": []},  # 无 project/task_group
                    },
                },
            },
            "rules": {},
        }
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, sample_config, out)  # sample_config lts=SRP_DAILY/GROUP_SPRD
        wb = openpyxl.load_workbook(out)
        ws = wb["tasks"]
        header = [c.value for c in ws[1]]
        proj_idx = header.index("项目名称")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert rows[0][proj_idx] == "SRP_DAILY", "旧 ts.json 应回退到 platform_config"


# ============================================================
# Manifest
# ============================================================

class TestGenerateManifest:

    def test_rule_codes_needed(self, sample_ts, sample_config, tmp_path):
        """rule_codes_needed = 取数 + 视图 + 参数变量"""
        out = tmp_path / "export_manifest.json"
        generate_manifest(sample_ts, sample_config, out)
        m = json.loads(out.read_text(encoding="utf-8"))
        assert m["rule_codes_needed"] == 3  # 1 取数 + 1 视图 + 1 参数

    def test_codes_filled_false(self, sample_ts, sample_config, tmp_path):
        """codes_filled 初始为 false"""
        out = tmp_path / "export_manifest.json"
        generate_manifest(sample_ts, sample_config, out)
        m = json.loads(out.read_text(encoding="utf-8"))
        assert m["codes_filled"] is False

    def test_task_name_derived(self, sample_ts, sample_config, tmp_path):
        """task_name 派生正确"""
        out = tmp_path / "export_manifest.json"
        generate_manifest(sample_ts, sample_config, out)
        m = json.loads(out.read_text(encoding="utf-8"))
        assert m["task_name"] == "task_dwb_xxx_f"
        assert m["job_name"] == "Pjob_dwb_xxx_f"

    def test_upstream_in_manifest(self, sample_ts, sample_config, tmp_path):
        """upstream_tasks 存在"""
        out = tmp_path / "export_manifest.json"
        generate_manifest(sample_ts, sample_config, out)
        m = json.loads(out.read_text(encoding="utf-8"))
        assert len(m["upstream_tasks"]) == 2
        assert m["upstream_tasks"][0]["schedule_task"] == "task_ods_order_f"


# ============================================================
# 工具函数
# ============================================================

class TestSplitSchemaTable:

    def test_with_schema(self):
        assert _split_schema_table("dws.dwb_xxx_f") == ("dws", "dwb_xxx_f")

    def test_without_schema(self):
        assert _split_schema_table("dwb_xxx_f") == ("", "dwb_xxx_f")
