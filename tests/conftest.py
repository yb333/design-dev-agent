"""公共 fixture：构造测试数据。

将 skill scripts 目录加入 sys.path，使测试可以直接 import 被测模块。
所有测试数据用 Python dict 构造，不依赖外部 xlsx 文件。
"""
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 将各 skill 的 scripts 目录加入 Python 路径
DESIGN_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-design" / "scripts"
CODING_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
# design-dev-shared：设计开发 agent 的公共代码库（dws_db.py 等）
DD_SHARED_REFS = Path(__file__).resolve().parent.parent / "skills" / "design-dev-shared" / "scripts"

for _p in (DESIGN_REFS, CODING_REFS, DD_SHARED_REFS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


import json
import pytest


# ============================================================
# 路径/产出相关 fixture
# ============================================================

@pytest.fixture
def fixtures_dir() -> Path:
    """返回测试数据 fixtures 目录。"""
    return PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def sample_ddl_sql(fixtures_dir: Path) -> str:
    """返回示例 DDL SQL 内容。"""
    return (fixtures_dir / "sample_ddl.sql").read_text(encoding="utf-8")


@pytest.fixture
def sample_etl_sql(fixtures_dir: Path) -> str:
    """返回示例 ETL SQL 内容。"""
    return (fixtures_dir / "sample_etl.sql").read_text(encoding="utf-8")


@pytest.fixture
def sample_mapping_json(fixtures_dir: Path) -> dict:
    """返回示例 mapping.json 字典。"""
    with open(fixtures_dir / "sample_mapping.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tmp_deliver(tmp_path):
    """临时产出目录，模拟 ddlc_design_dev/_internal 结构。"""
    d = tmp_path / "ddlc_design_dev"
    (d / "_internal").mkdir(parents=True, exist_ok=True)
    return d


# ============================================================
# 测试数据工厂函数
# 不依赖真实 xlsx，全部用 dict 构造。
# ============================================================

def make_rs_input(schema="dws", table="dwb_test_i", cn="测试表",
                  fields=None, sources=None, has_audit=True):
    """构造 rs_input.json 的 dict。

    Args:
        schema: 目标 schema。
        table: 目标表名（_i / _f / _d / 无后缀）。
        cn: 目标表中文名。
        fields: 字段列表，None 用默认（1 个业务字段）。
        sources: 源表列表，None 用默认（单源表）。
        has_audit: 是否追加 4 个审计字段。
    """
    if sources is None:
        sources = [{"source_schema": "ods", "source_table": "ods_test_f", "source_table_cn": "测试源表",
                    "source_alias": "t", "target_schema": schema, "target_table": table}]
    if fields is None:
        fields = [
            {"source_table": "ods_test_f", "source_column": "id", "source_type": "bigint",
             "transform_rule": "直接复制", "transform_detail": "-",
             "target_column": "id", "target_column_cn": "ID", "target_type": "bigint",
             "source_alias": "t", "remark": "主键"},
        ]
    if has_audit:
        audit = [
            {"transform_rule": "赋值", "transform_detail": "'N'", "target_column": "del_flag",
             "target_column_cn": "删除标识", "target_type": "NVARCHAR(1)", "remark": "审计字段"},
            {"transform_rule": "赋值", "transform_detail": "'${P_CYCLE_ID}'", "target_column": "crt_cycle_id",
             "target_column_cn": "创建批次", "target_type": "BIGINT", "remark": "审计字段"},
            {"transform_rule": "赋值", "transform_detail": "'${P_CYCLE_ID}'", "target_column": "last_upd_cycle_id",
             "target_column_cn": "更新批次", "target_type": "BIGINT", "remark": "审计字段"},
            {"transform_rule": "赋值", "transform_detail": "CURRENT_TIMESTAMP", "target_column": "dw_last_update_date",
             "target_column_cn": "更新时间", "target_type": "TIMESTAMP(0)", "remark": "审计字段"},
        ]
        fields = fields + audit

    # 推导 f_table 和 i_view（与 preprocess.build_rs_input 的推导规则一致）
    if table.endswith("_i"):
        f_table = table[:-2] + "_f"
        i_view = table
    elif table.endswith("_f"):
        f_table = table
        i_view = table[:-2] + "_i"
    else:
        f_table = table
        i_view = table + "_i"

    return {
        "meta": {
            "target": {
                "f_table": {"schema": schema, "table": f_table, "cn": cn},
                "i_view": {"schema": schema, "table": i_view, "cn": cn},
            },
            "grain": "每行一个测试记录",
            "load_strategy": {"strategy": "全量调度", "incremental_key": ""},
        },
        "source_tables": sources,
        "field_mappings": fields,
        "schedule": {"frequency": "T+1", "sla": "3:30", "strategy": "全量调度"},
        "dq_requirements": [],
    }


def make_design_decisions(rules=None, business_key=None, distribution_key=None, dq_rules=None,
                          business_key_design=None, tables=None, exemptions=None):
    """构造 design_decisions 的 dict。

    默认产出能通过 run_all_validations 全部新校验的合法 decisions。
    测试可通过传参注入特定坏值（如 business_key=[] 触发 N2）。
    """
    if rules is None:
        rules = [{
            "rule_code": "R0001", "rule_name": "测试规则", "scenario": "default",
            "exec_sequence": 1, "target_table": "dws.dwb_test_f", "is_view_step": False,
            "design_intent": "测试",
            "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
            "field_logics": {},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        }]
    bk = business_key if business_key is not None else ["id"]
    if business_key_design is None:
        business_key_design = {
            "input_key": list(bk),
            "adjusted": False,
            "reason": "沿用输入主键，产出粒度未变",
        }
    return {
        "rules": rules,
        "complexity_analysis": {
            "join_count": 1, "has_grain_change": False,
            "segmentation_decision": "不分段",
            "design_approach": "测试设计思路：单规则直灌目标表",
        },
        "distribution_key": distribution_key or ["id"],
        "business_key": bk,
        "business_key_design": business_key_design,
        "schedule": {"schedule_type": "daily", "cron": "0 30 3 * * ?"},
        "data_flow": {"dependencies": [], "schedule_groups": [{"sequence": 1, "rules": ["R0001"]}]},
        "dq_rules": dq_rules or [],
        "tables": tables or {},
        "exemptions": exemptions or [],
    }


def make_incremental_rs_input(schema="dws", table="dwb_test_i", cn="测试表",
                              drivers=None):
    """构造带增量驱动表的 rs_input（用于增量校验测试）。

    drivers: 驱动表列表，None 用默认两张（ods_test_f 按 update_time，ods_pay_f 按 dt）。
    """
    rs = make_rs_input(schema=schema, table=table, cn=cn)
    if drivers is None:
        drivers = [
            {"source_table": "ods_test_f", "incremental_key": "update_time"},
            {"source_table": "ods_pay_f", "incremental_key": "dt"},
        ]
    # 确保驱动表在 source_tables 里
    existing = {(s.get("source_table") or "").lower() for s in rs["source_tables"]}
    for d in drivers:
        short = (d.get("source_table") or "").split(".")[-1].lower()
        if short not in existing and (d.get("source_table") or "").lower() not in existing:
            rs["source_tables"].append({
                "source_schema": "ods", "source_table": d["source_table"],
                "source_table_cn": "增量源表", "source_alias": short[:3],
            })
    rs["schedule"]["incremental_key"] = "水位线"
    rs["schedule"]["incremental_tables"] = drivers
    return rs


def make_incremental_decisions(drivers_config):
    """构造增量场景的 design_decisions（多驱动表 → 多 extract + merge）。

    drivers_config: [{key, table, seq}] 驱动表配置，每张产出一个 extract 规则。
    返回的 decisions 默认能通过增量校验（N14-N17）。
    """
    rules = []
    seq = 1
    extract_codes = []
    for i, dc in enumerate(drivers_config):
        code = f"R{seq:04d}"
        rules.append({
            "rule_code": code, "rule_name": f"增量取数{dc['table']}", "scenario": "default",
            "exec_sequence": seq, "target_table": f"dws.tmp_{dc['table']}", "is_view_step": False,
            "step_type": "incremental_extract", "target_role": "intermediate",
            "produces_for": [], "reads": [],
            "field_targets": ["id"], "field_logics": {},
            "incremental": {
                "key": dc["key"],
                "filter": f"{dc['key']} >= '${{BIZ_DATE_START}}' AND {dc['key']} < '${{BIZ_DATE_END}}'",
                "init_filter": "1=1", "init_time_range": "ALL",
            },
        })
        extract_codes.append(code)
        seq += 1
    # merge 步骤
    merge_code = f"R{seq:04d}"
    rules.append({
        "rule_code": merge_code, "rule_name": "合并目标", "scenario": "default",
        "exec_sequence": seq, "target_table": "dws.dwb_test_f", "is_view_step": False,
        "step_type": "merge", "target_role": "target", "load_mode": "merge_into",
        "write_condition": "T.id=T1.id",
        "produces_for": [], "reads": [f"dws.tmp_{dc['table']}" for dc in drivers_config],
        "field_targets": ["id", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"],
        "field_logics": {},
        "grain": {"input": "源", "output": "目标", "change": "无"},
    })
    # 回填 produces_for
    for r in rules[:-1]:
        r["produces_for"] = [merge_code]
    return make_design_decisions(rules=rules)


def make_accumulate_decisions(overlap_fields=("b", "c"), extra_a=("a",), extra_b=("d", "e")):
    """构造累积共建场景的 design_decisions（两规则写同一中间表，字段重叠）。

    临时表有字段 a/b/c/d/e，规则1写 abc，规则2写 bcde（b/c 重叠）。
    """
    flds_r1 = list(extra_a) + list(overlap_fields)
    flds_r2 = list(overlap_fields) + list(extra_b)
    # 所有字段都要在 rs_input field_map 里——这里用单字段 id 的默认 rs_input 不够，
    # 调用方需配合 make_rs_input(fields=...) 造全字段。这里只造 decisions 结构。
    tmp_table = "dws.dwb_acc_tmp1"
    rules = [
        {
            "rule_code": "R0001", "rule_name": "来源A写入", "scenario": "default",
            "exec_sequence": 1, "target_table": tmp_table, "is_view_step": False,
            "step_type": "full", "target_role": "intermediate",
            "produces_for": ["R0003"], "reads": [],
            "field_targets": flds_r1, "field_logics": {},
            "load_mode": "no_delete",
        },
        {
            "rule_code": "R0002", "rule_name": "来源B追加(排重)", "scenario": "default",
            "exec_sequence": 2, "target_table": tmp_table, "is_view_step": False,
            "step_type": "full", "target_role": "intermediate",
            "produces_for": ["R0003"], "reads": [tmp_table],  # 自引用
            "field_targets": flds_r2, "field_logics": {},
            "load_mode": "no_delete",
            "dedup_strategy": {
                "target": tmp_table, "key": ["id"], "priority": "R0001 > R0002",
                "reason": "A来源优先",
            },
        },
        {
            "rule_code": "R0003", "rule_name": "装配目标", "scenario": "default",
            "exec_sequence": 3, "target_table": "dws.dwb_acc_f", "is_view_step": False,
            "step_type": "full", "target_role": "target",
            "produces_for": [], "reads": [tmp_table],
            "field_targets": list(extra_a) + list(overlap_fields) + list(extra_b),
            "field_logics": {},
            "grain": {"input": "源", "output": "目标", "change": "无"},
        },
    ]
    tables = {
        "dwb_acc_tmp1": {"build_mode": "accumulate", "distribution_key": ["id"]},
    }
    return make_design_decisions(rules=rules, tables=tables)


def make_ts_json(schema="dws", table="dwb_test_i", cn="测试表",
                 fields=None, business_key=None, rules=None, dq_rules=None):
    """直接构造一个完整的 ts.json dict（不走 assemble_ts）。"""
    rs = make_rs_input(schema=schema, table=table, cn=cn, fields=fields)
    dd = make_design_decisions(business_key=business_key, dq_rules=dq_rules)

    # 简化组装（不走 assemble_ts.py，直接拼）
    f_table = rs["meta"]["target"]["f_table"]
    i_view = rs["meta"]["target"]["i_view"]

    if rules is None:
        rules = {"R0001": {
            "rule_name": "测试规则", "scenario": "default", "exec_sequence": 1,
            "target_table": f_table["table"], "is_view_step": False, "design_intent": "测试",
            "source_tables": [{"schema": s["source_schema"], "table": s["source_table"], "alias": s.get("source_alias", "")} for s in rs["source_tables"]],
            "fields": [{"target_field": fm["target_column"], "field_type": fm.get("target_type", ""),
                        "field_comment": fm.get("target_column_cn", ""), "transform_type": "direct",
                        "source_fields": [{"table": fm.get("source_table", ""), "field": fm.get("source_column", ""), "alias": fm.get("source_alias", "")}],
                        "design_logic": fm.get("transform_detail", "")} for fm in rs["field_mappings"]],
            "field_count": len(rs["field_mappings"]),
        }}

    audit_fields = {
        "del_flag": {"type": "NVARCHAR(1)", "default": "'N'"},
        "crt_cycle_id": {"type": "BIGINT", "default": "'${P_CYCLE_ID}'"},
        "last_upd_cycle_id": {"type": "BIGINT", "default": "'${P_CYCLE_ID}'"},
        "dw_last_update_date": {"type": "TIMESTAMP(0)", "default": "CURRENT_TIMESTAMP"},
    }

    return {
        "version": "1.0.0", "spec_type": "ts",
        "meta": {
            "target": {"f_table": f_table, "i_view": i_view},
            "field_count": {"business": len(rs["field_mappings"]) - 4, "audit": 4, "total": len(rs["field_mappings"])},
            "source_tables": [{"schema": s["source_schema"], "table": s["source_table"], "table_cn": s.get("source_table_cn", ""), "alias": s.get("source_alias", "")} for s in rs["source_tables"]],
        },
        "design": {
            "audit_fields": audit_fields,
            "business_key": business_key or ["id"],
            "distribution_key": ["id"],
        },
        "rules": rules,
        "data_flow": {"tables": [], "dependencies": [], "schedule_groups": [{"sequence": 1, "rules": ["R0001"]}]},
        "dq_rules": dq_rules or [],
    }
