"""平台制品包 exporter 测试。

覆盖：
- shujia/lts 配置加载（2026-09-10 拆分）
- execution_tasks.xlsx（RULE/GroupVariables/TargetFields/空sheet）
- schedule_tasks.xlsx（tasks/jobs/taskParams）
- 编码全部留空（关键约束）
"""
import json
from pathlib import Path

import pytest
import openpyxl

# conftest 已把 coding scripts 加入 sys.path
from assemble_export import (
    load_shujia_config,
    load_lts_config,
    completeness_report_lines,
    resolve_config_by_schema,
    build_rule_rows,
    build_group_variables,
    build_target_fields,
    generate_execution_excel,
    generate_schedule_excel,
    validate_code_closure,
    validate_lts_package,
    AUDIT_FIELDS,
    RULE_COLUMNS,
    GROUPVARS_COLUMNS,
    TARGETFIELDS_COLUMNS,
    TASKS_COLUMNS,
    JOBS_COLUMNS,
    TASKPARAMS_COLUMNS,
    _RULE_COL,
    _JOBS_COL,
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
                        "project_name": "SRP_DAILY", "task_group": "GROUP_SPRD",
                        "job_name": "Pjob_dwb_xxx_f",
                        "cron": "0 30 3 * * ?",
                        "upstream": [
                            {"table": "ods_order_f", "task": "task_ods_order_f", "dep_type": "宽依赖"},
                            {"table": "dim_product_f", "task": "task_dim_product_f", "dep_type": "宽依赖"},
                        ],
                    },
                    "view": {
                        "task_name": "task_dwb_xxx_i",
                        "project_name": "SRP_DAILY", "task_group": "GROUP_SPRD",
                        "job_name": "Pjob_dwb_xxx_i",
                        "cron": "0 30 3 * * ?",
                        "upstream": [{"table": "dwb_xxx_f", "task": "task_dwb_xxx_f", "dep_type": "宽依赖"}],
                    },
                    "dq": {
                        "task_name": "task_dwb_xxx_f_dq",
                        "project_name": "SRP_DAILY", "task_group": "GROUP_SPRD",
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
                                "design_intent": "以订单事实表为主表左关联用户表装配宽表",
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
    """resolve_config_by_schema 返回的结构（术加段；LTS 配置独立 sample_lts）"""
    return {
        "shujia": {
            "appid": "APP001",
            "org_abbr": "crm_tenant",
            "project_code": "SRP_ETL",
            "project_cn": "ETL项目",
            "project_en": "ETL_Project",
            "datasource": "SRP_DWS",
            "business_owner": "zhangsan",
        },
    }


@pytest.fixture
def sample_lts():
    """load_lts_config 返回的结构（consts + 全局 dep_task_ids）"""
    return {
        "consts": {"cluster_local": "fin_pro", "db_name": "GAUSS_EDW_BFD_BNIL"},
        "dep_task_ids": {},
    }


@pytest.fixture
def etl_dir(tmp_path, sample_ts):
    """造一个 ETL SQL 文件"""
    d = tmp_path / "etl"
    d.mkdir()
    (d / "R0001.sql").write_text("SELECT 1 AS order_id, 100 AS order_amt", encoding="utf-8")
    return d


# ============================================================
# 配置加载
# ============================================================

class TestLoadPlatformConfig:

    def test_load_config(self, tmp_path):
        cfg_file = tmp_path / "shujia_config.json"
        cfg_file.write_text(json.dumps({
            "default": {"shujia": {"project_code": "XXX"}, "lts": {"project_name": "P"}},
        }), encoding="utf-8")
        result = load_shujia_config(str(cfg_file))
        assert result["default"]["shujia"]["project_code"] == "XXX"

    def test_missing_file_returns_empty(self):
        assert load_shujia_config("/nonexistent/path.json") == {}

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

    def test_lts_schema_override_and_global_ids(self, tmp_path):
        """★ load_lts_config 三段结构：schema_mappings.{schema}.consts 覆盖 default.consts；
        dep_task_ids 全局隔离（不参与 schema 覆盖——依赖的任务唯一，与 schema 无关）。"""
        raw = {
            "default": {"project_name": "SRP_DAILY", "task_group": "GROUP_SPRD",  # 路径键（assemble_ts 消费，此处应无感）
                        "cluster_local": "fin_pro", "db_name": "DB_A"},
            "schema_mappings": {
                "fin": {"project_name": "FIN_DAILY", "db_name": "DB_FIN"},  # 只覆盖差异键
            },
            "dep_task_ids": {"c1|i|g|t": "111"},
        }
        cfg_file = tmp_path / "lts_config.json"
        cfg_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        r_fin = load_lts_config(str(cfg_file), "fin")
        assert r_fin["consts"] == {"cluster_local": "fin_pro", "db_name": "DB_FIN"}
        assert r_fin["dep_task_ids"] == {"c1|i|g|t": "111"}   # schema 段不顶掉全局表
        r_other = load_lts_config(str(cfg_file), "other_schema")
        assert r_other["consts"] == {"cluster_local": "fin_pro", "db_name": "DB_A"}
        assert r_other["dep_task_ids"] == {"c1|i|g|t": "111"}

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
        """空配置返回空结构（appid 由调用方注入；LTS 走独立 load_lts_config）"""
        result = resolve_config_by_schema({}, "slas")
        assert result == {"shujia": {"appid": ""}}

    def test_tenant_block_overrides(self):
        """★ 租户块：shujia_tenants[appid] 的 org_abbr/datasource 覆盖 schema 级；
        project_cn/business_owner 也住租户块（appid→项目，不随 schema 变）"""
        raw = {
            "default": {"shujia": {"datasource": "SCHEMA_LEVEL_DS", "project_code": "P1"}},
            "shujia_tenants": {
                "APP001": {"org_abbr": "crm_tenant", "datasource": "TENANT_DS",
                           "project_cn": "CRM域", "business_owner": "zhangsan"},
            },
        }
        result = resolve_config_by_schema(raw, "slprd", appid="APP001")
        assert result["shujia"]["org_abbr"] == "crm_tenant"
        assert result["shujia"]["datasource"] == "TENANT_DS"   # 租户级覆盖 schema 级
        assert result["shujia"]["project_code"] == "P1"        # 非租户属性不受影响
        assert result["shujia"]["appid"] == "APP001"
        assert result["shujia"]["project_cn"] == "CRM域"       # 租户块身份全集
        assert result["shujia"]["business_owner"] == "zhangsan"

    def test_tenant_only_config(self):
        """★ 收敛形态：只有 shujia_tenants 一块（example 的最终形态）也能跑通"""
        raw = {
            "shujia_tenants": {
                "APP001": {"org_abbr": "t1", "datasource": "DS1",
                           "project_cn": "域A", "business_owner": "u1"},
            },
        }
        result = resolve_config_by_schema(raw, "dws", appid="APP001")
        assert result["shujia"]["project_cn"] == "域A"

    def test_no_appid_no_tenant_merge(self):
        """没传 appid → 不做租户合并，datasource 走 schema 级"""
        raw = {
            "default": {"shujia": {"datasource": "SCHEMA_LEVEL_DS"}},
            "shujia_tenants": {"APP001": {"org_abbr": "crm_tenant"}},
        }
        result = resolve_config_by_schema(raw, "slprd")
        assert result["shujia"]["datasource"] == "SCHEMA_LEVEL_DS"
        assert "org_abbr" not in result["shujia"]


# ============================================================
# RULE sheet
# ============================================================

class TestBuildRuleRows:

    def test_rule_row_count(self, sample_ts, sample_config, etl_dir):
        """RULE 行数 = 取数规则 + 参数变量（视图不发术加规则行）"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        # 1 取数 + 1 参数变量 = 2
        assert len(rows) == 2

    def test_view_does_not_create_rule_row(self, sample_ts, sample_config, etl_dir):
        """★ 回归守护：有 i_view 时不产生视图术加规则行（视图 DDL 走 ddl/ 通道部署）"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        for row in rows:
            sql = row[_RULE_COL["(生成的）查询语句1"]]
            assert "CREATE VIEW" not in sql and "CREATE OR REPLACE VIEW" not in sql
            assert row[_RULE_COL["目标表"]] != sample_ts["meta"]["target"]["i_view"]["table"]

    def test_placeholder_codes(self, sample_ts, sample_config, etl_dir):
        """★ 编码为占位符：规则编码 = ts 规则码 / PV000N；规则组编码 = GR_{组英文名}"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        etl_row, pv_row = rows[0], rows[1]
        assert etl_row[_RULE_COL["规则编码"]] == "R0001"
        assert etl_row[_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f"
        assert pv_row[_RULE_COL["规则编码"]] == "PV0001"
        assert pv_row[_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f"

    def test_tenant_columns(self, sample_ts, sample_config, etl_dir):
        """★ 租户ID = appid、组织英文简称 = 租户名（shujia_tenants 解析）"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        for row in rows:
            assert row[_RULE_COL["租户ID"]] == "APP001"
            assert row[_RULE_COL["组织英文简称"]] == "crm_tenant"

    def test_project_only_cn_filled(self, sample_ts, sample_config, etl_dir):
        """★ 项目只填中文名；编码/英文名出厂留空（内网脚本按中文名补齐）。
        sample_config 故意带 project_code/project_en（旧配置兼容）——验证被忽略不进产物。"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        for row in rows:
            assert row[_RULE_COL["项目中文名"]] == "ETL项目"
            assert row[_RULE_COL["项目编码"]] == ""
            assert row[_RULE_COL["项目英文名"]] == ""
            assert row[_RULE_COL["子项目编码"]] == ""
            assert row[_RULE_COL["子项目中文名"]] == ""
            assert row[_RULE_COL["子项目英文名"]] == ""

    def test_rule_desc_from_design_intent(self, sample_ts, sample_config, etl_dir):
        """规则描述 ← design_intent；备注留空"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        etl_row = rows[0]
        assert etl_row[_RULE_COL["规则描述"]] == "以订单事实表为主表左关联用户表装配宽表"
        assert etl_row[_RULE_COL["备注"]] == ""

    def test_long_sql_split_columns(self, sample_ts, sample_config, sample_lts, tmp_path):
        """★ 超长 SQL 分列到查询语句1~N，拼接逐字还原"""
        etl_dir = tmp_path / "etl"
        etl_dir.mkdir()
        long_sql = "SELECT " + ", ".join(f"col_{i} AS c{i}" for i in range(3000))  # > 30000
        (etl_dir / "R0001.sql").write_text(long_sql, encoding="utf-8")
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        row = rows[0]
        parts = [row[_RULE_COL[f"(生成的）查询语句{n}"]] for n in range(1, 10)]
        non_empty = [p for p in parts if p]
        assert len(non_empty) >= 2                        # 确实分列了
        assert "".join(non_empty) == long_sql             # 拼接逐字还原

    def test_etl_query_in_statement(self, sample_ts, sample_config, etl_dir):
        """取数规则的查询语句列含 SQL 内容"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        etl_row = rows[0]
        assert "SELECT 1 AS order_id" in etl_row[_RULE_COL["(生成的）查询语句1"]]

    def test_exec_sequence_filled(self, sample_ts, sample_config, etl_dir):
        """执行序列从 ts 透传（决定加工拓扑）"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        etl_row = rows[0]
        assert etl_row[_RULE_COL["执行序列"]] == "1"  # sample_ts R0001 exec_sequence=1

    def test_param_rule_form(self, sample_ts, sample_config, etl_dir):
        """参数变量规则形态：类型 12、执行序列 -1、查询语句/运行条件留空"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        pv_row = rows[-1]
        assert pv_row[_RULE_COL["规则类型"]] == "12"
        assert pv_row[_RULE_COL["规则中文名称"]] == "参数变量规则"
        assert pv_row[_RULE_COL["规则英文名称"]] == "Parameter Variable Rule"
        assert pv_row[_RULE_COL["创建方式"]] == "1"
        assert pv_row[_RULE_COL["执行序列"]] == "-1"
        assert pv_row[_RULE_COL["运行条件"]] == ""
        assert pv_row[_RULE_COL["(生成的）查询语句1"]] == ""

    def test_separate_init_group_gets_own_pv_row(self, sample_ts, sample_config, etl_dir):
        """separate init 规则组有自己的参数变量行（每规则组一条，占位码独立）"""
        (etl_dir / "INIT_R0001.sql").write_text(
            "SELECT 1 AS order_id, 100 AS order_amt WHERE dt <= '20260101'", encoding="utf-8"
        )
        sample_ts["init"] = {
            "mode": "derive", "group_mode": "separate",
            "rules": {"INIT_R0001": {
                "rule_name": "XXX汇总(初始化)", "exec_sequence": 1,
                "target_table": "dwb_xxx_f",                 "load_mode": "truncate_table",
            }},
        }
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        # 1 取数 + 1 init 取数 + 主组 pv + init 组 pv = 4
        assert len(rows) == 4
        init_row = rows[1]
        assert init_row[_RULE_COL["规则编码"]] == "INIT_R0001"
        assert init_row[_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f_init"
        assert init_row[_RULE_COL["规则组英文名称"]] == "dwb_xxx_f_init"
        pv_rows = [r for r in rows if r[_RULE_COL["规则类型"]] == "12"]
        assert len(pv_rows) == 2
        by_code = {r[_RULE_COL["规则编码"]]: r for r in pv_rows}
        assert set(by_code) == {"PV0001", "PV0002"}
        assert by_code["PV0001"][_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f"
        assert by_code["PV0002"][_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f_init"

    def test_constants_filled(self, sample_ts, sample_config, etl_dir):
        """固定常量正确"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        etl_row = rows[0]
        assert etl_row[_RULE_COL["数据库类型"]] == "GaussDB"
        assert etl_row[_RULE_COL["删除模式"]] == "1"
        assert etl_row[_RULE_COL["调度类型"]] == "0"

    def test_column_count_is_82(self, sample_ts, sample_config, etl_dir):
        """RULE 每行 82 列"""
        rows = build_rule_rows(sample_ts, sample_config, etl_dir)
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

    def test_rule_code_is_pv_placeholder(self, sample_ts):
        """★ 规则编码挂参数变量规则行的占位码 PV0001"""
        rows = build_group_variables(sample_ts)
        for row in rows:
            assert row[0] == "PV0001"

    def test_desc_filled(self, sample_ts):
        """描述 ← exec_params.desc"""
        rows = build_group_variables(sample_ts)
        assert rows[0][8] == "批次号"

    def test_gv_per_group_separate_init(self, sample_ts):
        """separate init：每个规则组各挂一份变量（分别指向该组 pv 行占位码）"""
        sample_ts["init"] = {
            "mode": "derive", "group_mode": "separate",
            "rules": {"INIT_R0001": {
                "rule_name": "XXX汇总(初始化)", "exec_sequence": 1,
                "target_table": "dwb_xxx_f",             }},
        }
        rows = build_group_variables(sample_ts)
        codes = {row[0] for row in rows}
        assert codes == {"PV0001", "PV0002"}

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
        """来源字段固定 s.字段 形态（s 是平台标准别名）；无源留空"""
        rows = build_target_fields(sample_ts)
        by_field = {row[1]: row for row in rows}
        assert by_field["order_amt"][2] == "s.amount"
        assert by_field["order_id"][2] == "s.order_id"
        assert by_field["order_amt"][5] == ""  # 别名不填

    def test_no_source_field_empty(self):
        """无源（COUNT(1) 等表达式派生）来源字段留空"""
        ts = {"rules": {"R0001": {"target_table": "dwb_xxx_f", "fields": [
            {"target_field": "record_cnt", "source_fields": []},
        ]}}}
        rows = build_target_fields(ts)
        assert rows[0][2] == ""

    def test_rule_code_is_ts_code(self, sample_ts):
        """★ 规则编码 = ts 规则码（占位，与 RULE 行对应）"""
        rows = build_target_fields(sample_ts)
        for row in rows:
            assert row[0] == "R0001"


# ============================================================
# Excel 生成（端到端）
# ============================================================

class TestGenerateExecutionExcel:

    def test_10_sheets(self, sample_ts, sample_config, etl_dir, tmp_path):
        """execution Excel 有 10 个 sheet"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, out)
        wb = openpyxl.load_workbook(out)
        assert len(wb.sheetnames) == 10
        assert "RULE" in wb.sheetnames
        assert "GroupVariables" in wb.sheetnames
        assert "TargetFields" in wb.sheetnames

    def test_empty_sheets_have_headers_only(self, sample_ts, sample_config, etl_dir, tmp_path):
        """空 sheet 只有表头"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["ModelRelations"]
        assert ws.max_row == 1  # 只有表头行

    def test_rule_sheet_has_data(self, sample_ts, sample_config, etl_dir, tmp_path):
        """RULE sheet 有数据行"""
        out = tmp_path / "execution_tasks.xlsx"
        generate_execution_excel(sample_ts, sample_config, etl_dir, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["RULE"]
        assert ws.max_row == 3  # 表头 + 1 取数 + 1 参数变量（无视图行）

    def test_closure_ok(self, sample_ts, sample_config, etl_dir):
        """★ 三处占位编码闭合：正常数据无问题"""
        rule_rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        gv_rows = build_group_variables(sample_ts)
        tf_rows = build_target_fields(sample_ts)
        assert validate_code_closure(rule_rows, gv_rows, tf_rows) == []

    def test_closure_catches_dangling(self, sample_ts, sample_config, etl_dir):
        """★ 悬挂引用被抓住：GV/TF 引用了 RULE 没有的编码"""
        rule_rows = build_rule_rows(sample_ts, sample_config, etl_dir)
        gv_rows = build_group_variables(sample_ts)
        tf_rows = build_target_fields(sample_ts)
        tf_rows.append(["R9999", "ghost_field", "s.ghost", "0", "", "", "", ""])
        problems = validate_code_closure(rule_rows, gv_rows, tf_rows)
        assert any("R9999" in p for p in problems)

    def test_closure_blocks_generation(self, sample_ts, sample_config, etl_dir, tmp_path, monkeypatch):
        """★ 闭合校验失败阻断生成（fail loud）"""
        import assemble_export
        monkeypatch.setattr(assemble_export, "build_target_fields",
                            lambda ts: [["R9999", "ghost", "s.ghost", "0", "", "", "", ""]])
        out = tmp_path / "execution_tasks.xlsx"
        with pytest.raises(ValueError, match="R9999"):
            generate_execution_excel(sample_ts, sample_config, etl_dir, out)


class TestGenerateScheduleExcel:
    """LTS 制品生成（设计依据 docs/platform/lts-制品生成设计.md §四/§五/§十）。"""

    def _rows(self, wb, sheet):
        ws = wb[sheet]
        header = [c.value for c in ws[1]]
        return header, list(ws.iter_rows(min_row=2, values_only=True))

    def _jobs_by(self, wb, **kw):
        """按列值筛 jobs 行，返回 (header, rows)。"""
        header, rows = self._rows(wb, "jobs")
        for col, val in kw.items():
            idx = header.index(col)
            rows = [r for r in rows if r[idx] == val]
        return header, rows

    def test_3_sheets(self, sample_ts, sample_config, sample_lts, tmp_path):
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        assert wb.sheetnames == ["tasks", "jobs", "taskParams"]

    def test_tasks_has_f_view_dq(self, sample_ts, sample_config, sample_lts, tmp_path):
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        assert wb["tasks"].max_row == 4  # 表头 + F + 视图 + DQ

    def test_jobs_composition_full_asset(self, sample_ts, sample_config, sample_lts, tmp_path):
        """案例 A（全量资产）：f=主job+2tskdep；view=占位job+tskdep；dq=主job+tskdep。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._rows(wb, "jobs")
        types = [r[header.index("job类型")] for r in rows]
        assert types.count("url") == 2        # f/dq 主 job（全量无 GETDATE）
        assert types.count("database") == 1   # view 占位 job
        assert types.count("tskdep") == 4

    def test_main_job_shape(self, sample_ts, sample_config, sample_lts, tmp_path):
        """主 job：异步 POST 8 键正确形态 + ${V_URL} + 工程属性 + 通用三列。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job类型="url")
        assert len(rows) == 1
        r = rows[0]
        assert r[header.index("job名称")] == "Pjob_dwb_xxx_f"
        assert r[header.index("job的父节点名称")] == "start"  # 无 init=全量
        assert r[header.index("执行路径信息")] == "${V_URL}"
        assert r[header.index("job调用方法")] == "POST"
        assert r[header.index("job超时时间")] == "60"
        assert r[header.index("job重试次数")] == "3"
        assert r[header.index("job重试间隔")] == "60"
        assert r[header.index("job是否跳过清场")] == "跟随任务"
        assert r[header.index("job超时处理")] == "一次邮件提醒"
        assert r[header.index("job执行节点")] == "任一节点"
        assert r[header.index("job异常处理方式")] == "fail"
        assert r[header.index("参数空值校验")] == "否"
        params = json.loads(r[header.index("job参数")])
        assert params["headers"] == "Content-Type:application/json;charset=UTF-8"
        assert params["invokingMode"] == "异步"
        assert params["appToken"] == "${V_TOKEN}"
        assert params["appId"] == "${V_APPID}"
        assert params["authenticationType"] == "手动输入"
        assert params["timeout"] == 10
        run_params = json.loads(params["jobRunParams"])
        assert run_params["batch_number"] == "${V_BATCH_NUMBER}"
        assert run_params["group_code"] == "${V_GROUP_CODE}"
        assert run_params["sch_from"] == "${V_SCH_FROM}"
        assert {"name": "P_CYCLE_ID", "type": "constants", "value": "${V_CYCLE_ID}"} in run_params["params"]

    def test_appid_not_literal_in_job_params(self, sample_ts, sample_config, sample_lts, tmp_path):
        """主 job appId 是 ${V_APPID} 变量引用；appid 字面量只在 taskParams 的 V_APPID 行。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job类型="url")
        assert "APP001" not in rows[0][header.index("job参数")]
        ws = wb["taskParams"]
        vals = {r[3]: r[4] for r in ws.iter_rows(min_row=2, values_only=True)
                if r[2] == "task_dwb_xxx_f"}
        assert vals["V_APPID"] == "APP001"

    def test_view_placeholder_database_job(self, sample_ts, sample_config, sample_lts, tmp_path):
        """视图任务 job = database 占位查询（SELECT 1 WHERE 1=2）+ 6 键 + 10/3/1。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_i", job类型="database")
        assert len(rows) == 1
        r = rows[0]
        assert r[header.index("job名称")] == "Pjob_dwb_xxx_i"
        assert r[header.index("执行路径信息")] == "SELECT 1 FROM dws.dwb_xxx_i WHERE 1 = 2"
        assert r[header.index("job调用方法")] == "sql"
        assert r[header.index("job超时时间")] == "10"
        assert r[header.index("job是否跳过清场")] == "否"
        params = json.loads(r[header.index("job参数")])
        assert params["schema"] == "dws"
        assert params["dbsource"] == "[*].[GAUSS_EDW_BFD_BNIL]"
        assert params["datasourceTypeName"] == "gauss200"

    def test_tskdep_row_current_task_and_path(self, sample_ts, sample_config, sample_lts, tmp_path):
        """tskdep 行归属恒=当前任务；4 段路径=appid|项目组|任务组|任务名（上游缺省回退当前任务）。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, job类型="tskdep", job名称="task_ods_order_f")
        assert len(rows) == 1
        r = rows[0]
        assert r[header.index("项目名称")] == "SRP_DAILY"     # 当前任务（非上游）
        assert r[header.index("任务组名称")] == "GROUP_SPRD"
        assert r[header.index("任务名称")] == "task_dwb_xxx_f"
        assert r[header.index("job的父节点名称")] == "Pjob_dwb_xxx_f"
        assert r[header.index("执行路径信息")] == "APP001|SRP_DAILY|GROUP_SPRD|task_ods_order_f"
        params = json.loads(r[header.index("job参数")])
        assert params["type"] == "tskdep"
        assert params["mainJobName"] == "Pjob_dwb_xxx_f"
        assert params["depJobName"] == "end"                  # 同集群恒 end
        assert params["name"] == params["depTaskName"] == "task_ods_order_f"
        assert params["productionClusterName"] == "fin_pro"
        assert params["crossClusterDepKey"] == ""
        assert params["crossClusterSrcName"] == ""            # 同集群照样本①留空
        assert params["itemName"] == "SRP_DAILY"
        assert params["taskGroupName"] == "GROUP_SPRD"
        assert "depTaskId" not in params                      # 仅跨集群有

    def test_tskdep_cross_cluster(self, sample_ts, sample_config, sample_lts, tmp_path):
        """跨集群 5 段：cluster/job 输入直传；depTaskId 显式表命中；name=depJobName=远端 job 名。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["meta"]["schedule"]["tasks"]["f"]["upstream"] = [{
            "table": "ods_remote", "task": "TASK_REMOTE_T", "dep_type": "宽依赖",
            "env": "edw_pro", "app": "com.huawei.x", "project": "ITEM_X", "group": "GRP_X",
            "job": "PJob_REMOTE_J",
        }]
        cfg = json.loads(json.dumps(sample_config))
        sample_lts["dep_task_ids"] = {"edw_pro|ITEM_X|GRP_X|TASK_REMOTE_T": "20224946"}
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, cfg, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, job类型="tskdep", job名称="PJob_REMOTE_J")
        assert len(rows) == 1
        r = rows[0]
        assert r[header.index("项目名称")] == "SRP_DAILY"     # 行归属仍是当前任务
        assert r[header.index("执行路径信息")] == "edw_pro|com.huawei.x|ITEM_X|GRP_X|TASK_REMOTE_T"
        params = json.loads(r[header.index("job参数")])
        assert params["depTaskId"] == "20224946"
        assert params["name"] == params["depJobName"] == "PJob_REMOTE_J"  # 跨集群=upstream.job 引用名（id 是 task 级，键不含 job）
        assert params["depTaskName"] == "TASK_REMOTE_T"
        assert params["productionClusterName"] == "edw_pro"   # 被依赖任务的集群
        assert params["crossClusterDepName"] == "edw_pro"
        assert params["crossClusterSrcName"] == "fin_pro"     # 本集群
        assert params["crossClusterDepKey"] == "edw|pro|"
        assert params["itemName"] == "ITEM_X"
        assert params["taskGroupName"] == "GRP_X"

    def test_tskdep_cross_cluster_missing_id_skips(self, sample_ts, sample_config, sample_lts, tmp_path, capsys):
        """缺 id → 跳过该依赖行不阻断（制品可导入），返回+打印跳过清单带四段键。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["meta"]["schedule"]["tasks"]["f"]["upstream"] = [
            {"table": "ods_remote", "task": "TASK_REMOTE_T", "env": "edw_pro",
             "app": "com.huawei.x", "project": "ITEM_X", "group": "GRP_X",
             "job": "PJob_REMOTE_J"},
            {"table": "ods_ok", "task": "TASK_OK_T", "env": "edw_pro",
             "app": "com.huawei.x", "project": "ITEM_X", "group": "GRP_X",
             "job": "PJob_OK"},
        ]
        cfg = json.loads(json.dumps(sample_config))
        sample_lts["dep_task_ids"] = {"edw_pro|ITEM_X|GRP_X|TASK_OK_T": "42"}
        out = tmp_path / "schedule_tasks.xlsx"
        skipped = generate_schedule_excel(ts, cfg, out, sample_lts)
        assert skipped == [("task_dwb_xxx_f", "edw_pro|ITEM_X|GRP_X|TASK_REMOTE_T")]
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, job类型="tskdep")
        names = [r[header.index("job名称")] for r in rows]
        assert "PJob_REMOTE_J" not in names      # 缺 id 行不生成
        assert "PJob_OK" in names                # 有 id 行照常
        out_text = capsys.readouterr().out
        assert "edw_pro|ITEM_X|GRP_X|TASK_REMOTE_T" in out_text and "已跳过" in out_text

    def test_tskdep_cross_cluster_missing_job_fails(self, sample_ts, sample_config, sample_lts, tmp_path):
        """跨集群缺 job 字段 → fail-loud（输入直传不推导）。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["meta"]["schedule"]["tasks"]["f"]["upstream"] = [{
            "table": "ods_remote", "task": "TASK_REMOTE_T", "env": "edw_pro",
            "app": "com.huawei.x", "project": "ITEM_X", "group": "GRP_X",
        }]
        out = tmp_path / "schedule_tasks.xlsx"
        with pytest.raises(ValueError, match="缺远端 job 名"):
            generate_schedule_excel(ts, sample_config, out, sample_lts)

    def test_virtual_dep_row(self, sample_ts, sample_config, sample_lts, tmp_path):
        """虚拟依赖：${V_URL_virtualDependence} + 全空 8 键 + query 形态 jobName 自指。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["meta"]["schedule"]["tasks"]["f"]["upstream"] = [{
            "table": "src_t", "task": "TASK_SRC", "dep_type": "虚拟依赖",
            "app": "com.huawei.so.master_data", "project": "IT_产品", "group": "IT_组",
            "job": "PJob_EXT_2500_F_T_D2S",
        }]
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, job类型="url", job名称="PJob_EXT_2500_F_T_D2S")
        assert len(rows) == 1
        r = rows[0]
        assert r[header.index("执行路径信息")] == "${V_URL_virtualDependence}"
        assert r[header.index("job的父节点名称")] == "start"
        assert r[header.index("job调用方法")] == "POST"
        params = json.loads(r[header.index("job参数")])
        assert params["headers"] == "" and params["appToken"] == "" and params["appId"] == ""
        assert params["authenticationType"] == "无"
        assert params["jobRunParams"] == (
            "clusterName=${P_CLUSTER_EDW_PRO}&appId=com.huawei.so.master_data"
            "&itemName=IT_产品&taskGroupName=IT_组&taskName=TASK_SRC"
            "&jobName=PJob_EXT_2500_F_T_D2S&begin=${BEGIN_TIMES}&end=${END_TIMES}")

    def test_virtual_dep_missing_job_fails(self, sample_ts, sample_config, sample_lts, tmp_path):
        ts = json.loads(json.dumps(sample_ts))
        ts["meta"]["schedule"]["tasks"]["f"]["upstream"] = [{
            "table": "src_t", "task": "TASK_SRC", "dep_type": "虚拟依赖",
            "app": "a", "project": "b", "group": "c",
        }]
        out = tmp_path / "schedule_tasks.xlsx"
        with pytest.raises(ValueError, match="虚拟依赖缺 job 全名"):
            generate_schedule_excel(ts, sample_config, out, sample_lts)

    def test_incremental_getdate_and_parent(self, sample_ts, sample_config, sample_lts, tmp_path):
        """案例 B（增量）：init 段存在 → GETDATE 行 + 主 job 父=GETDATE + 变量设置桥接。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["init"] = {"group_mode": "separate", "rules": {"R0001_INIT": {"target_table": "dws.dwb_xxx_f"}}}
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job名称="GETDATE")
        assert len(rows) == 1
        g = rows[0]
        assert g[header.index("job类型")] == "database"
        assert g[header.index("job的父节点名称")] == "start"
        sql = g[header.index("执行路径信息")]
        assert "DW_LAST_UPDATE_DATE" in sql and "${V_CYCLE_ID}" in sql
        vs = g[header.index("job变量设置")]
        assert vs == "P_DW_LAST_UPDATE_DATE=DW_LAST_UPDATE_DATE;P_CUR_CYCLE_ID=CUR_CYCLE_ID"
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job类型="url")
        assert rows[0][header.index("job的父节点名称")] == "GETDATE"

    def test_p_flag_supply_chain(self, sample_ts, sample_config, sample_lts, tmp_path):
        """校验5：inline init 引用 ${P_FLAG} 但无 V_FLAG 声明 → 阻断；声明后全链路生成。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["init"] = {"group_mode": "inline", "rules": {}}
        out = tmp_path / "schedule_tasks.xlsx"
        with pytest.raises(ValueError, match="P_FLAG"):
            generate_schedule_excel(ts, sample_config, out, sample_lts)
        # designer 在 lts_params 声明 V_FLAG（含取值）→ 通过
        ts["meta"]["schedule"]["lts_params"].append(
            {"lts_var": "V_FLAG", "etl_param": "P_FLAG", "value": "1", "desc": "增量标志"})
        generate_schedule_excel(ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job名称="GETDATE")
        assert rows[0][header.index("job变量设置")].endswith(";P_FLAG=P_FLAG")
        header, rows = self._jobs_by(wb, 任务名称="task_dwb_xxx_f", job类型="url")
        run_params = json.loads(json.loads(rows[0][header.index("job参数")])["jobRunParams"])
        assert {"name": "P_FLAG", "type": "constants", "value": "${V_FLAG}"} in run_params["params"]
        ws = wb["taskParams"]
        vals = {r[3]: r[4] for r in ws.iter_rows(min_row=2, values_only=True)
                if r[2] == "task_dwb_xxx_f"}
        assert vals["V_FLAG"] == "1"

    def test_taskparams_base_set(self, sample_ts, sample_config, sample_lts, tmp_path):
        """每任务 8 项基础参数；值模板为定稿字面量（方案 A）。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        ws = wb["taskParams"]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert ws.max_row == 1 + 3 * 8   # f/view/dq × 8 基础参数
        vals = {r[3]: r[4] for r in rows if r[2] == "task_dwb_xxx_f"}
        assert vals["V_BATCH_NUMBER"] == "$getJobUUID(jobUUID)"
        assert vals["V_SCH_FROM"] == "LTS"
        assert vals["V_CYCLE_ID"] == "$getTaskPlanTime(plantime,@@yyyyMMdd000000@@,-24*60*60)"
        assert vals["BEGIN_TIMES"] == "$getTaskPlanTime(plantime,@@yyyy-MM-dd 00:00:00@@)"
        assert vals["END_TIMES"] == "$getTaskPlanTime(plantime,@@23:59:59@@)"
        assert vals["V_DW_LAST_UPDATE_DATE"] == "$getCurrentTime(@@yyyy-MM-dd HH:mm:ss@@,0)"
        assert vals["V_GROUP_CODE"] == "GR_dwb_xxx_f"   # 资产级规则组占位符（与 RULE sheet 同款，内网取码回填）
        assert vals["V_APPID"] == "APP001"

    def test_taskparams_init_group_code(self, sample_ts, sample_config, sample_lts, tmp_path):
        """separate init 任务执行 init 规则组：V_GROUP_CODE 占位 GR_{表}_init（f/view/dq 用主组）。"""
        ts = json.loads(json.dumps(sample_ts))
        ts["init"] = {"group_mode": "separate", "rules": {"R0001_INIT": {"target_table": "dwb_xxx_f"}}}
        ts["meta"]["schedule"]["tasks"]["init"] = {
            "task_name": "task_dwb_xxx_f_init", "job_name": "Pjob_dwb_xxx_f_init",
            "cron": "0 30 3 * * ?", "upstream": [],
            "project_name": "SRP_DAILY", "task_group": "GROUP_SPRD"}
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        ws = wb["taskParams"]
        pairs = [(r[2], r[4]) for r in ws.iter_rows(min_row=2, values_only=True) if r[3] == "V_GROUP_CODE"]
        mains = [v for task, v in pairs if not task.endswith("_init")]
        inits = [v for task, v in pairs if task.endswith("_init")]
        assert mains and all(v == "GR_dwb_xxx_f" for v in mains)        # f/view/dq 主组占位
        assert inits == ["GR_dwb_xxx_f_init"]                           # init 任务用 init 组占位

    def test_project_group_from_ts_json(self, sample_config, tmp_path):
        """★ ts.json 的 task 带 project_name/task_group 时，exporter 直接用。"""
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
        cfg = {"shujia": {"appid": "APP001"}}
        lts_cfg = {"consts": {"cluster_local": "fin_pro", "db_name": "DB"}, "dep_task_ids": {}}
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, cfg, out, lts_cfg)
        wb = openpyxl.load_workbook(out)
        ws = wb["tasks"]
        header = [c.value for c in ws[1]]
        proj_idx = header.index("项目名称")
        group_idx = header.index("任务组名称")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert rows[0][proj_idx] == "TS_PROJ_F"
        assert rows[0][group_idx] == "TS_GRP_F"
        assert rows[1][proj_idx] == "TS_PROJ_V"
        assert rows[2][proj_idx] == "TS_PROJ_DQ"

    def test_project_group_missing_marks_pending(self, sample_ts, sample_config, sample_lts, tmp_path):
        """旧 ts.json 没有 project/task_group -> "待配置"（platform_config.lts 兜底已随拆分退役）。"""
        ts = json.loads(json.dumps(sample_ts))
        for kind in ("f", "view", "dq"):
            ts["meta"]["schedule"]["tasks"][kind].pop("project_name", None)
            ts["meta"]["schedule"]["tasks"][kind].pop("task_group", None)
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(ts, sample_config, out, sample_lts)
        wb = openpyxl.load_workbook(out)
        ws = wb["tasks"]
        header = [c.value for c in ws[1]]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert rows[0][header.index("项目名称")] == "待配置"


class TestCompletenessReport:
    """完整度报告（固定格式待补清单——闸口②后固定二选一的问题来源，agent 只转述）。"""

    def test_basic_full_asset(self, sample_ts):
        lines = completeness_report_lines(sample_ts, [])
        text = "\n".join(lines)
        assert "[制品完整度报告]" in text and "占位符形态" in text
        assert "项目编码 / 项目英文名" in text
        assert "子项目编码 / 中文名 / 英文名" in text
        assert "GR_dwb_xxx_f（占位" in text
        assert "V_GROUP_CODE = GR_dwb_xxx_f" in text
        assert "跨集群依赖完整（无跳过）" in text
        assert "GR_dwb_xxx_f_init" not in text

    def test_with_init_and_skipped(self, sample_ts):
        ts = json.loads(json.dumps(sample_ts))
        ts["init"] = {"group_mode": "separate", "rules": {"R0001_INIT": {}}}
        lines = completeness_report_lines(ts, [("task_dwb_xxx_f", "edw_pro|I|G|T")])
        text = "\n".join(lines)
        assert "GR_dwb_xxx_f_init（占位）" in text
        assert "V_GROUP_CODE = GR_dwb_xxx_f / GR_dwb_xxx_f_init" in text
        assert 'lts_config dep_task_ids 补 "edw_pro|I|G|T"' in text
        assert "任务 task_dwb_xxx_f" in text


class TestSupplementParams:
    """选项2固定清单项：--sub-project-cn/--group-code/--init-group-code 真值注入。"""

    def test_group_code_real_value(self, sample_ts, sample_config, sample_lts, etl_dir, tmp_path):
        """规则组编码真值：RULE sheet 与 LTS taskParams 两处同值（不再占位）。"""
        out = tmp_path / "schedule_tasks.xlsx"
        generate_schedule_excel(sample_ts, sample_config, out, sample_lts,
                                group_codes={"main": "URG_000123"})
        wb = openpyxl.load_workbook(out)
        ws = wb["taskParams"]
        vals = {r[3]: r[4] for r in ws.iter_rows(min_row=2, values_only=True)}
        assert vals["V_GROUP_CODE"] == "URG_000123"

        rows = build_rule_rows(sample_ts, sample_config, etl_dir, group_codes={"main": "URG_000123"})
        codes = {r[_RULE_COL["规则组编码"]] for r in rows}
        assert "URG_000123" in codes and "GR_dwb_xxx_f" not in codes

    def test_sub_project_cn(self, sample_ts, sample_config, etl_dir):
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, sub_project_cn="订单子域")
        assert all(r[_RULE_COL["子项目中文名"]] == "订单子域" for r in rows)

    def test_group_codes_empty_keeps_placeholder(self, sample_ts, sample_config, etl_dir):
        rows = build_rule_rows(sample_ts, sample_config, etl_dir, group_codes={})
        assert all(r[_RULE_COL["规则组编码"]] == "GR_dwb_xxx_f" for r in rows)


class TestLtsValidators:

    def _row(self, **kw):
        row = [""] * len(JOBS_COLUMNS)
        for col, val in kw.items():
            row[_JOBS_COL[col]] = val
        return row

    def test_v_ref_closure(self):
        """校验1：job 引用 taskParams 未定义的 ${V_XXX} → 报出（平台注入变量豁免）。"""
        rows = [self._row(任务名称="t1", job名称="j1",
                          执行路径信息="${V_URL} ${V_UNKNOWN}")]
        problems = validate_lts_package({}, [], rows, {"V_CYCLE_ID"})
        assert any("V_UNKNOWN" in p for p in problems)
        assert not any("V_URL" in p for p in problems)   # 平台注入豁免

    def test_parent_closure(self):
        """校验2：父节点须为 start/EMPTY 或本任务 job 名。"""
        rows = [self._row(任务名称="t1", job名称="j1", job的父节点名称="ghost")]
        problems = validate_lts_package({}, [], rows, set())
        assert any("ghost" in p for p in problems)
        ok = [self._row(任务名称="t1", job名称="j1", job的父节点名称="start"),
              self._row(任务名称="t1", job名称="j2", job的父节点名称="j1")]
        assert validate_lts_package({}, [], ok, set()) == []

    def test_p_flag_chain(self):
        """校验5：inline init 需要 V_FLAG→P_FLAG 全链路。"""
        ts = {"init": {"group_mode": "inline"}}
        rows = [self._row(任务名称="t1", job名称="j1")]
        problems = validate_lts_package(ts, [], rows, {"V_CYCLE_ID"})
        assert sum("P_FLAG" in p or "V_FLAG" in p for p in problems) == 2
        lts_params = [{"lts_var": "V_FLAG", "etl_param": "P_FLAG", "value": "1"}]
        assert validate_lts_package(ts, lts_params, rows, {"V_CYCLE_ID", "V_FLAG"}) == []


# ============================================================
# 工具函数
# ============================================================

class TestSplitSchemaTable:

    def test_with_schema(self):
        assert _split_schema_table("dws.dwb_xxx_f") == ("dws", "dwb_xxx_f")

    def test_without_schema(self):
        assert _split_schema_table("dwb_xxx_f") == ("", "dwb_xxx_f")
