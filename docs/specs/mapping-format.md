# Mapping 文件格式说明

> 本文档说明 **mapping.xlsx 的 2 个 sheet** 的列定义与填写规范。
> 输入整体结构（mapping + RS 如何组合、rs_input.json 如何生成）见 [rs-input-format.md](./rs-input-format.md)。

> **变更说明**：mapping 从原 6 个 sheet 精简为 **2 个 sheet**。原调度配置/执行平台/设计配置/数据处理步骤 sheet 的内容已移至 RS 文档（见 `docs/templates/RS模板.md`）。

---

## 文件结构总览

mapping.xlsx 只包含 **2 个 sheet**：

| Sheet | 名称 | 必须 | 说明 |
|------|------|------|------|
| 1 | 实体级 mapping | ✅ | 源表与目标表的关联关系（表级） |
| 2 | 属性级 mapping | ✅ | 字段级别的映射规则（字段级） |

> 调度/执行平台/设计配置等信息**不在 mapping**，见 RS 文档的标记块。

---

## Sheet 1: 实体级 mapping

定义源表与目标表之间的关联关系。

### 列定义

| 列名 | 必须 | 说明 | 示例 |
|------|------|------|------|
| 源表 schema | ✅ | 源表所属 schema | `fin_dwl_cnb` |
| 源表物理表名 | ✅ | 源表物理表名 | `dwl_con_pu_mtr_f` |
| 源表中文名 | ❌ | 源表中文名 | `合同pu指标表` |
| 目标表 schema | ✅ | 目标表所属 schema | `fin_dwl_cnb` |
| 目标表物理表名 | ✅ | 目标表物理表名 | `dwl_con_pu_any_f` |
| 目标表中文名 | ❌ | 目标表中文名 | `合同pu分析表` |
| JOIN 条件 | ❌ | 源表与主表的关联条件，主表填"主表" | `left join on t.contract_key = f.contract_key` |
| 源表别名 | ✅ | 区分同一源表的不同关联实例 | `t`、`f`、`inv_mtr` |
| 备注 | ❌ | 补充说明 | `为了获取排除非洲场景发票内容范围` |

### 示例

| 源表 schema | 源表物理表名 | 源表中文名 | 源表别名 | JOIN 条件 | 备注 |
|---|---|---|---|---|---|
| fin_dwl_cnb | dwl_con_pu_mtr_f | 合同pu指标表 | t | 主表 | |
| fin_dwl_cnb | dwl_con_any_f | 合同分析表 | f | left join on t.contract_key = f.contract_key | |

### 源表别名说明

当同一张源表被关联多次（不同关联实例），用别名区分。别名在属性级 mapping 中用于标识字段来源。

### ⚠️ 已移除的列

以下列原在实体级 mapping，现已移至 RS 文档：

| 原列名 | 去向 |
|--------|------|
| 调度任务名称（schedule_task） | RS `@upstream` |
| 执行路径（exec_path） | RS `@upstream` |
| 依赖参数（dep_job_params） | RS `@upstream` |

---

## Sheet 2: 属性级 mapping

定义字段级别的映射规则：每个目标字段从哪个源字段来、怎么转换。

### 列定义

| 列名 | 必须 | 说明 | 示例 |
|------|------|------|------|
| 目标字段名 | ✅ | 目标表字段名 | `contract_no` |
| 目标字段中文名 | ❌ | 目标字段注释 | `合同号` |
| 目标字段类型 | ✅ | 目标字段数据类型 | `nvarchar(500)` |
| 来源表别名 | ✅ | 对应实体级 mapping 的源表别名 | `t` |
| 来源字段名 | ✅ | 源表字段名 | `contract_no` |
| 来源字段类型 | ❌ | 源字段数据类型 | `nvarchar(500)` |
| 映射规则 | ✅ | 转换类型：直取/聚合/行转列/赋值/派生等 | `直取`、`行转列`、`聚合` |
| 转换规则说明 | ❌ | **自然语言描述**加工逻辑，**不含业务术语** | `rpt_code='fbt_0001'对应设备订货金额，按合同+pu汇总` |

### 示例

| 目标字段 | 目标类型 | 来源别名 | 来源字段 | 映射规则 | 转换规则说明 |
|---|---|---|---|---|---|
| contract_no | nvarchar(500) | t | contract_no | 直取 | - |
| equip_org_amt_usd | numeric(38,10) | t | rpt_value_usd | 行转列 | rpt_code='fbt_0001'对应设备订货USD，按合同+pu汇总 |
| inv_tol_amt_usd | numeric(38,10) | inv_mtr | inv_inst_amt_usd | 聚合 | 对发票金额求和，排除非洲发票 |

### ⚠️ 转换规则说明的填写要求

- **必须用自然语言**，不要写 SQL 表达式（如 `SUM(CASE WHEN...)`）
- **不含业务术语**（前置预检会校验）—— BA 能看懂的描述，不要用内部黑话
- 描述"算什么、什么口径"，不描述"SQL怎么拼"
- 复杂逻辑（行转列/聚合/多步）必须写说明，简单直取可填"-"

---

## 填写案例

完整填写案例见 [`docs/templates/examples/连接层粒度转换案例mapping.xlsx`](../templates/examples/)。

---

## 解析后产物（mapping.json）

mapping.xlsx 经 `excel_parser` 解析后产出 `mapping.json`，结构见 [rs-input-format.md §三](./rs-input-format.md)。

解析后 mapping.json 只包含：
- `source_tables`（实体级，纯关联关系）
- `field_mappings`（属性级，字段映射）

不再包含调度/平台/设计配置（这些从 RS 提取）。
