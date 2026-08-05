#!/usr/bin/env python3
"""生成能力陷阱用例 T1/T2/T3 + 各自的干净对照版。

每个用例目录产出：mapping.xlsx + RS.md + checks.yaml。
mapping.xlsx 沿用 002 的两表结构（实体级 + 属性级），保证 preprocess 能解析。

设计原则：
- 埋雷版：输入里故意留诱导犯错的细节，断言"正确行为契约"
- 干净对照版：同结构不埋雷，断言正常期望，防过度警觉误报
"""
import openpyxl
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent / "cases"

# ============================================================
# 通用：写 mapping.xlsx（两张表：实体级 + 属性级）
# ============================================================

ENTITY_HEADERS = [
    "序号", "分组", "源表schema*", "源表中文名", "源表物理表名*",
    "源表别名*", "目标表逻辑schema*", "目标表中文名", "目标表物理名称*",
    "取数规则", "关联&限定条件", "备注", "数据库类型",
]
ATTR_HEADERS = [
    "序号", "分组", "源Schema", "源表物理表名", "源表物理表别名",
    "源字段中文名", "源表字段名", "源表字段类型", "映射规则*", "映射表达式",
    "目标字段名*", "目标字段中文名", "目标字段类型", "备注", "数据标准",
]


def _audit_rows(scene="default", src_schema="ods", src_table="ods_xxx", alias="a"):
    """标准 4 审计字段属性行。"""
    return [
        (None, scene, src_schema, src_table, alias, None, None, None, "赋值", "'N'",
         "del_flag", "删除标识", "NVARCHAR(1)", "审计字段", None),
        (None, scene, src_schema, src_table, alias, None, None, None, "赋值", "'${P_CYCLE_ID}'",
         "crt_cycle_id", "创建批次ID", "BIGINT", "审计字段", None),
        (None, scene, src_schema, src_table, alias, None, None, None, "赋值", "'${P_CYCLE_ID}'",
         "last_upd_cycle_id", "最后更新批次ID", "BIGINT", "审计字段", None),
        (None, scene, src_schema, src_table, alias, None, None, None, "赋值", "CURRENT_TIMESTAMP",
         "dw_last_update_date", "数仓最后更新时间", "TIMESTAMP(0) WITHOUT TIME ZONE", "审计字段", None),
    ]


def write_mapping(path: Path, entity_rows: list, attr_rows: list):
    """写 mapping.xlsx。entity_rows/attr_rows 不含表头。"""
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "实体级mapping"
    ws1.append(ENTITY_HEADERS)
    for i, row in enumerate(entity_rows, 1):
        ws1.append((i, *row[1:]))
    ws2 = wb.create_sheet("属性级mapping")
    ws2.append(ATTR_HEADERS)
    for i, row in enumerate(attr_rows, 1):
        ws2.append((i, *row[1:]))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ============================================================
# T1：头行整合主键发散（business_key 判断）
# 目标表是头+行整合宽表（ods_order 头表 + ods_order_line 行表）。
# 埋雷：mapping 主键备注只标了头表 order_id；RS 写"一行=订单的一个商品行"。
# 期望：designer 识别粒度=订单行级，business_key 扩展为 [order_id, line_id]。
# ============================================================

T1_BURIED_RS = """# RS - 订单行明细宽表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_order_line_wide_i |
| 资产描述 | 订单行明细整合宽表 |
| 业务对象 | 订单行 |
| 逻辑数据实体 | 一行=一个订单的一个商品行 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |
"""

T1_CLEAN_RS = """# RS - 订单行明细宽表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_order_line_wide_i |
| 资产描述 | 订单行明细整合宽表 |
| 业务对象 | 订单行 |
| 逻辑数据实体 | 一行=一个订单的一个商品行 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |
"""


def build_t1():
    """T1：头行整合主键发散。"""
    # 实体级：两张源表（头表 + 行表）
    entity = [
        (1, "default", "ods", "订单头表", "ods_order", "h", "dws", "订单行明细宽表",
         "dwb_order_line_wide_i", None, "主表", None, None),
        (2, "default", "ods", "订单商品行表", "ods_order_line", "l", "dws", "订单行明细宽表",
         "dwb_order_line_wide_i", None, "JOIN l.order_id = h.order_id", None, None),
    ]
    # 属性级：头表字段 + 行表字段
    # 埋雷：只给 order_id 标"主键"（头表主键），line_id 没标主键
    attr = [
        # 头表字段
        (1, "default", "ods", "ods_order", "h", "订单ID", "order_id", "VARCHAR(64)",
         "直接复制", "-", "order_id", "订单ID", "VARCHAR(64)", "主键", None),
        (2, "default", "ods", "ods_order", "h", "客户ID", "cust_id", "VARCHAR(64)",
         "直接复制", "-", "cust_id", "客户ID", "VARCHAR(64)", None, None),
        # 行表字段
        (3, "default", "ods", "ods_order_line", "l", "行ID", "line_id", "VARCHAR(64)",
         "直接复制", "-", "line_id", "行ID", "VARCHAR(64)", None, None),
        (4, "default", "ods", "ods_order_line", "l", "商品ID", "product_id", "VARCHAR(64)",
         "直接复制", "-", "product_id", "商品ID", "VARCHAR(64)", None, None),
        (5, "default", "ods", "ods_order_line", "l", "行金额", "line_amt", "DECIMAL(18,2)",
         "直接复制", "-", "line_amt", "行金额", "DECIMAL(18,2)", None, None),
    ]
    attr += _audit_rows(src_table="ods_order", alias="h")

    base = CASES_DIR / "T1_order_line_key_diverge"
    write_mapping(base / "mapping.xlsx", entity, attr)
    (base / "RS.md").write_text(T1_BURIED_RS, encoding="utf-8")
    (base / "checks.yaml").write_text(_T1_BURIED_CHECKS, encoding="utf-8")

    # 干净对照版：mapping 主键正确标了 [order_id, line_id]
    attr_clean = list(attr)
    # 把 line_id 那行（index 2）的备注改成"主键"
    attr_clean[2] = (3, "default", "ods", "ods_order_line", "l", "行ID", "line_id", "VARCHAR(64)",
                     "直接复制", "-", "line_id", "行ID", "VARCHAR(64)", "主键", None)
    clean = CASES_DIR / "T1_order_line_key_diverge_clean"
    write_mapping(clean / "mapping.xlsx", entity, attr_clean)
    (clean / "RS.md").write_text(T1_CLEAN_RS, encoding="utf-8")
    (clean / "checks.yaml").write_text(_T1_CLEAN_CHECKS, encoding="utf-8")


_T1_BURIED_CHECKS = """# T1 能力陷阱：头行整合主键发散
# 埋雷：mapping 主键只标了头表 order_id，但目标表粒度是订单行级（头+行整合）。
# 契约：designer 应识别粒度=订单行级，business_key 扩展为 [order_id, line_id]。
case:
  name: "T1 头行整合主键发散（陷阱）"
  target_table: "dwb_order_line_wide_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  # ✅ must: business_key 必须扩展为 [order_id, line_id]
  business_key: [order_id, line_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  load_mode_valid: true
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_order, ods.ods_order_line]

code:
  R0001:
    fields_required: [order_id, cust_id, line_id, product_id, line_amt, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_order, ods.ods_order_line]
    group_by_granularity: [order_id, line_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""

_T1_CLEAN_CHECKS = """# T1 干净对照：mapping 主键正确标了 [order_id, line_id]
# 正常期望：business_key == [order_id, line_id]（和埋雷版断言一致，防误报）
case:
  name: "T1 头行整合主键（干净对照）"
  target_table: "dwb_order_line_wide_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  business_key: [order_id, line_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  load_mode_valid: true
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_order, ods.ods_order_line]

code:
  R0001:
    fields_required: [order_id, cust_id, line_id, product_id, line_amt, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_order, ods.ods_order_line]
    group_by_granularity: [order_id, line_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""


# ============================================================
# T2：RS 标增量但配全量（增量识别）
# 埋雷：RS 正文化用一段话标了"每日增量更新，基于 update_time 取昨日新增"，
#       但 L07 调度表写"全量调度"，mapping 主键稳定字段简单，无增量列提示。
# 期望：designer 主动扫 RS 识别增量，产出至少一条规则 load_mode != truncate_table。
# 干净对照版：RS 写"全量调度"，断言所有规则 load_mode == truncate_table。
# ============================================================

T2_BURIED_RS = """# RS - 客户活跃度汇总表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_cust_active_d_i |
| 资产描述 | 客户活跃度汇总表 |
| 业务对象 | 客户 |
| 逻辑数据实体 | 每行一个客户 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |

## 补充说明

本表每日增量更新，基于源表 update_time 字段取昨日新增及变更数据，仅处理增量部分，不做全量重刷。
"""

T2_CLEAN_RS = """# RS - 客户活跃度汇总表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_cust_active_d_i |
| 资产描述 | 客户活跃度汇总表 |
| 业务对象 | 客户 |
| 逻辑数据实体 | 每行一个客户 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |

## 补充说明

本表采用全量调度策略，每日全量重刷，不涉及增量识别。
"""


def build_t2():
    """T2：RS 标增量但配全量。"""
    entity = [
        (1, "default", "ods", "客户事实表", "ods_cust_fact", "c", "dws", "客户活跃度汇总表",
         "dwb_cust_active_d_i", None, "主表", None, None),
    ]
    attr = [
        (1, "default", "ods", "ods_cust_fact", "c", "客户ID", "cust_id", "VARCHAR(64)",
         "直接复制", "-", "cust_id", "客户ID", "VARCHAR(64)", "主键", None),
        (2, "default", "ods", "ods_cust_fact", "c", "客户名称", "cust_name", "VARCHAR(200)",
         "直接复制", "-", "cust_name", "客户名称", "VARCHAR(200)", None, None),
        (3, "default", "ods", "ods_cust_fact", "c", "活跃分值", "active_score", "DECIMAL(18,2)",
         "数据加工", "按客户汇总活跃分值", "active_score", "活跃分值", "DECIMAL(18,2)", None, None),
    ]
    attr += _audit_rows(src_table="ods_cust_fact", alias="c")

    base = CASES_DIR / "T2_rs_incremental_misled"
    write_mapping(base / "mapping.xlsx", entity, attr)
    (base / "RS.md").write_text(T2_BURIED_RS, encoding="utf-8")
    (base / "checks.yaml").write_text(_T2_BURIED_CHECKS, encoding="utf-8")

    clean = CASES_DIR / "T2_rs_incremental_misled_clean"
    write_mapping(clean / "mapping.xlsx", entity, attr)
    (clean / "RS.md").write_text(T2_CLEAN_RS, encoding="utf-8")
    (clean / "checks.yaml").write_text(_T2_CLEAN_CHECKS, encoding="utf-8")


_T2_BURIED_CHECKS = """# T2 能力陷阱：RS 标增量但配全量
# 埋雷：RS 补充说明写"每日增量更新，基于 update_time 取昨日新增"，但 L07 调度表写"全量调度"。
# 契约：designer 应识别增量，产出至少一条规则 load_mode != truncate_table + incremental 段。
case:
  name: "T2 RS标增量但配全量（陷阱）"
  target_table: "dwb_cust_active_d_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  business_key: [cust_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  # ✅ must: load_mode 应为增量模式（至少一条非 truncate_table）
  # ❌ must_not: 所有规则 load_mode == truncate_table（用 load_mode_valid 配合 incremental 检查）
  load_mode_valid: true
  # 增量检查：load_mode≠truncate_table 时必须有 incremental 段
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_cust_fact]

code:
  R0001:
    fields_required: [cust_id, cust_name, active_score, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_cust_fact]
    group_by_granularity: [cust_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""

_T2_CLEAN_CHECKS = """# T2 干净对照：RS 明确全量调度
# 正常期望：所有规则 load_mode == truncate_table（全量重刷）
case:
  name: "T2 RS全量调度（干净对照）"
  target_table: "dwb_cust_active_d_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  business_key: [cust_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  load_mode_valid: true
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_cust_fact]

code:
  R0001:
    fields_required: [cust_id, cust_name, active_score, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_cust_fact]
    group_by_granularity: [cust_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""


# ============================================================
# T3：数据源缺口（拒绝沉默假设）
# 埋雷：字段 customer_level 口径依赖 dwd_customer_rfm 表，但 mapping 可用源表里没这张表。
#       给一张名字相近的 dim_customer（有 level_cd 字段）诱导用错来源。
# 期望：designer 发现缺口并标注，不默默用 dim_customer.level_cd 替代。
# 断言：
#   ✅ must: design_intent/join_safety 含缺口标注关键词
#   ❌ must_not: customer_level 映射到 dim_customer（用 field_not_mapped_from）
# ============================================================

T3_BURIED_RS = """# RS - 客户价值汇总表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_cust_value_i |
| 资产描述 | 客户价值汇总表 |
| 业务对象 | 客户 |
| 逻辑数据实体 | 每行一个客户 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |

## 字段口径说明

| 字段 | 口径 |
|------|------|
| customer_level | 客户价值分级，取自 dwd_customer_rfm 表的 rfm_level 字段（按客户最近购买频次和金额分档） |
"""

T3_CLEAN_RS = """# RS - 客户价值汇总表

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | dws |
| 资产名称 | dwb_cust_value_i |
| 资产描述 | 客户价值汇总表 |
| 业务对象 | 客户 |
| 逻辑数据实体 | 每行一个客户 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|--------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |

## 字段口径说明

| 字段 | 口径 |
|------|------|
| customer_level | 客户价值分级，取自 dim_customer 表的 level_cd 字段 |
"""


def build_t3():
    """T3：数据源缺口。"""
    # 实体级：主表 ods_cust + 一张相近维表 dim_customer（诱导项）
    # 注意：口径要的 dwd_customer_rfm 不在可用源表里
    entity = [
        (1, "default", "ods", "客户主表", "ods_cust", "c", "dws", "客户价值汇总表",
         "dwb_cust_value_i", None, "主表", None, None),
        (2, "default", "dim", "客户维度表", "dim_customer", "d", "dws", "客户价值汇总表",
         "dwb_cust_value_i", None, "LEFT JOIN d.cust_id = c.cust_id", None, None),
    ]
    attr = [
        (1, "default", "ods", "ods_cust", "c", "客户ID", "cust_id", "VARCHAR(64)",
         "直接复制", "-", "cust_id", "客户ID", "VARCHAR(64)", "主键", None),
        (2, "default", "ods", "ods_cust", "c", "客户名称", "cust_name", "VARCHAR(200)",
         "直接复制", "-", "cust_name", "客户名称", "VARCHAR(200)", None, None),
        # 埋雷字段：customer_level 口径要 dwd_customer_rfm.rfm_level，
        # 但源里只有名字相近的 dim_customer.level_cd
        (3, "default", "dim", "dim_customer", "d", "等级编码", "level_cd", "VARCHAR(20)",
         "直接复制", "-", "customer_level", "客户分级", "VARCHAR(20)", None, None),
    ]
    attr += _audit_rows(src_schema="ods", src_table="ods_cust", alias="c")

    base = CASES_DIR / "T3_missing_data_source"
    write_mapping(base / "mapping.xlsx", entity, attr)
    (base / "RS.md").write_text(T3_BURIED_RS, encoding="utf-8")
    (base / "checks.yaml").write_text(_T3_BURIED_CHECKS, encoding="utf-8")

    # 干净对照版：口径表写"取自 dim_customer.level_cd"（和可用源表一致，无缺口）
    clean = CASES_DIR / "T3_missing_data_source_clean"
    write_mapping(clean / "mapping.xlsx", entity, attr)
    (clean / "RS.md").write_text(T3_CLEAN_RS, encoding="utf-8")
    (clean / "checks.yaml").write_text(_T3_CLEAN_CHECKS, encoding="utf-8")


_T3_BURIED_CHECKS = """# T3 能力陷阱：数据源缺口
# 埋雷：customer_level 口径要 dwd_customer_rfm，但可用源表里只有名字相近的 dim_customer。
# 契约：designer 应发现缺口并标注，不默默用 dim_customer.level_cd 替代。
case:
  name: "T3 数据源缺口（陷阱）"
  target_table: "dwb_cust_value_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  business_key: [cust_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  load_mode_valid: true
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_cust, dim.dim_customer]
  # ✅ must: customer_level 不能映射到 dim_customer（应发现缺口）
  field_not_mapped_from:
    field: customer_level
    not_from_table: dim_customer

code:
  R0001:
    fields_required: [cust_id, cust_name, customer_level, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_cust]
    group_by_granularity: [cust_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""

_T3_CLEAN_CHECKS = """# T3 干净对照：口径与可用源表一致（无缺口）
# 正常期望：customer_level 映射到 dim_customer.level_cd（可用源表能覆盖口径）
case:
  name: "T3 数据源齐全（干净对照）"
  target_table: "dwb_cust_value_f"
  rules_expected: [R0001]

artifacts:
  ts_json_top_keys: [version, meta, design, rules, data_flow]
  audit_fields_count: 4
  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
  each_rule_has_load_mode: true
  ddl_rollback_paired: true
  no_select_star_in_view: true

design:
  business_key: [cust_id]
  field_targets_cover_rs_input: true
  field_targets_no_cross_rule_dup: true
  load_mode_valid: true
  join_safety_strategy_when_not_unique: true
  segmentation_reason_when_segmented: true
  source_tables_required: [ods.ods_cust, dim.dim_customer]

code:
  R0001:
    fields_required: [cust_id, cust_name, customer_level, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    join_tables: [ods.ods_cust]
    group_by_granularity: [cust_id]
    case_when_must_have_else: true
    no_select_star: true
    audit_fields_in_select: true
"""


if __name__ == "__main__":
    build_t1()
    build_t2()
    build_t3()
    print("✓ 生成 6 个用例目录：T1/T2/T3 + 各自 _clean")
    for d in sorted(CASES_DIR.iterdir()):
        if d.name.startswith("T"):
            files = sorted(f.name for f in d.iterdir())
            print(f"  {d.name}: {files}")
