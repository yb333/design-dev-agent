# ETL 技术规格（TS）

> 目标表：`{{schema}}.{{target_table}}`（{{target_cn}}） · 生成：{{date}}

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `{{schema}}.{{f_table}}`（{{f_cn}}，物理表） |
| **I 视图** | `{{schema}}.{{i_view}}`（F表镜像，对外消费） |
| **目标粒度** | {{grain}} |
| **写入策略** | {{load_strategy}} |
| **分布键** | {{distribution_key}} |
| **字段统计** | 业务 {{biz_count}} + 审计 4 = 总计 {{total_count}} |
| **场景数** | {{scenario_count}} |
| **规则数** | {{rule_count}} |

**来源表**：

| # | 表名 | 中文名 | 别名 | 层 |
|---|------|--------|------|-----|
| 1 | {{schema}}.{{table}} | {{cn}} | {{alias}} | {{layer}} |

---

## 2. 表模型设计

### 2.1 目标表

| 项目 | 值 |
|------|-----|
| schema | {{schema}} |
| F 表 | {{f_table}}（存数据） |
| I 视图 | {{i_view}}（F表镜像，对外查询） |
| 表类型 | {{table_type}} |
| 分布键 | {{distribution_key}} |
| 分区 | {{partition}} |

### 2.2 中间表

| 中间逻辑 | 类型 | 名称 | 粒度 | 用途 |
|----------|------|------|------|------|
| {{mid_name}} | {{CTE/物理表}} | {{table_name}} | {{grain}} | {{purpose}} |

---

## 3. 复杂度分析与分段决策

### 3.1 复杂度指标

| 因素 | 值 | 阈值 | 说明 |
|------|-----|------|------|
| JOIN 表数量 | {{join_count}} | >12 触发分段 | {{join_note}} |
| 粒度变化 | {{grain_change}} | 有即声明 | {{grain_change_detail}} |
| 多步骤加工字段 | {{multi_step}} | ≥5 触发分段 | {{multi_step_note}} |
| 聚合后关联 | {{agg_after_join}} | — | — |
| 复杂关联链 | {{chain_level}} | ≥3 触发分段 | — |

### 3.2 分段与中间表决策

**分段结论**：{{segmentation_decision}}

**中间表决策**：

| 中间逻辑 | 决策 | 简要依据 |
|----------|------|----------|
| {{mid_logic}} | {{CTE内联/物理表}} | {{reason}} |

---

## 4. 规则详情

### {{rule_code}} · {{rule_name}}

| 项目 | 内容 |
|------|------|
| 场景 | {{scenario}} |
| 执行序 | {{seq}} |
| 产出表 | `{{target_table}}` |
| 设计意图 | {{design_intent}} |
| 字段数 | {{field_count}} |

**CTE**：

| CTE | 用途 | 来源表 |
|-----|------|--------|
| {{cte_name}} | {{purpose}} | {{sources}} |

**粒度**：

| 输入粒度 | 输出粒度 | 变化 |
|----------|----------|------|
| {{input_grain}} | {{output_grain}} | {{change}} |

**关联策略**：

| 别名 | JOIN | 关联条件 | 限定 |
|------|------|----------|------|
| {{alias}} | {{join_type}} | {{condition}} | {{filter}} |

**关联安全分析**：

| 被关联表 | JOIN键唯一 | 对齐策略 |
|----------|-----------|----------|
| {{table}} | {{unique}} | {{strategy}} |

**字段概要**：

| 转换类型 | 数量 | 示例字段 |
|----------|------|----------|
| direct | {{n}} | {{examples}} |
| pivot | {{n}} | {{examples}} |
| aggregate | {{n}} | {{examples}} |
| assign | 4 | del_flag, crt_cycle_id, ... |

---

## 5. 数据流向图

```mermaid
flowchart LR
    {{source_nodes}}
    {{rule_node}}["{{rule_code}}<br/>{{rule_name}}"]
    {{target_node}}["{{target_table}}"]
    {{source_nodes}} --> {{rule_node}}
    {{rule_node}} --> {{target_node}}
```

**血缘关系表**：

| from | to | 类型 | 中间表 |
|------|-----|------|--------|
| {{from_rule}} | {{to_rule}} | data_flow | {{mid_table}} |

---

## 6. 调度配置

| 配置项 | 值 | 来源 |
|--------|-----|------|
| 调度任务 | {{task_name}} | {{source}} |
| 调度周期 | {{cron}}（{{cron_desc}}） | {{source}} |
| 任务组 | {{task_group}} | {{source}} |
| 执行参数 | {{exec_params}} | {{source}} |
| 执行平台 | {{project_code}} / {{datasource}} | {{source}} |

**上游依赖**：
{{upstream_tasks}}

---

## 7. 数据质量检查（DQ）

{{dq_content}}
