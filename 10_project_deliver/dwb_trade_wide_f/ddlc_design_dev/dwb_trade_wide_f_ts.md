# ETL 技术规格(TS)

> 目标表: `dws.dwb_trade_wide_f`(交易宽表) - 生成 2026-08-04T22:00:07

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `dws.dwb_trade_wide_f`（交易宽表） |
| **I 视图** | `dws.dwb_trade_wide_i`（F表镜像，对外查询） |
| **业务主键** | order_id |
| **写入策略** | 全量（可随时重刷） |
| **字段统计** | 8 |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | ods.ods_trade_order_di | 订单明细 | o |

---

## 2. 表模型设计

| 表名 | 类型 | 分布 | 分区 | 字段数 | 说明 |
|------|------|------|------|--------|------|
| `dwb_trade_wide_f` | 目标F表 | HASH(order_id) | — | 8 | 交易宽表 |
| `dwb_trade_wide_i` | 直封视图 | — | — | 同F表 | F表镜像，对外查询 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 | 阈值 |
|------|-----|------|
| JOIN 表数量 | 0 | >12 触发分段 |
| 粒度变化 | 无 | 有即评估分段 |
| 多步骤加工字段 | 0 | ≥5 触发分段 |
| 聚合后关联 | 否 | 是即评估分段 |

**分段结论**: **不分段**

> 单源主表无关联（join_count=0），无粒度变化，所有字段为直接复制或审计赋值，单条 INSERT 即可完成，无需中间表/分段。

---

## 4. 规则详情

### R0001 - 交易宽表主表加载

| 项目 | 内容 |
|------|------|
| 执行序 | 1 |
| 产出表 | `dws.dwb_trade_wide_f` |
| 写入方式 | truncate_table |
| 设计意图 | 单源主表直加载，无关联无加工，全量覆盖写入目标F表。 |
| 字段数 | 8 |

---

## 5. 数据流向

```mermaid
flowchart TD

  step_R0001("R0001 / 交易宽表主表加载")
  src_ods_trade_order_di["ods_trade_order_di<br/><small>ods</small>"]
  tbl_dws_dwb_trade_wide_f["dws.dwb_trade_wide_f"]

  src_ods_trade_order_di --> step_R0001
  step_R0001 --> tbl_dws_dwb_trade_wide_f

  classDef source fill:#dbeafe,stroke:#3b82f6,stroke-width:1.5px,color:#1e3a5f
  classDef step fill:#ede9fe,stroke:#8b5cf6,stroke-width:1.5px,color:#4c1d95
  classDef intermediate fill:#f1f5f9,stroke:#64748b,stroke-width:1.5px,color:#334155,stroke-dasharray:5 3
  classDef target fill:#dcfce7,stroke:#22c55e,stroke-width:2.5px,color:#166534
  classDef view fill:#e0e7ff,stroke:#6366f1,stroke-width:1.5px,color:#3730a3,stroke-dasharray:5 3
  class step_R0001 step
  class src_ods_trade_order_di source
  class tbl_dws_dwb_trade_wide_f target
```

---

## 6. 调度配置

### F 表调度

| 配置项 | 值 |
|--------|-----|
| 调度任务 | DWS_DWB_TRADE_WIDE_F |
| 调度周期 | 0 0 3 * * ? |

**LTS 参数**:

| LTS 变量 | 赋值给 ETL 参数 | 说明 |
|----------|----------------|------|
| V_CYCLE_ID | P_CYCLE_ID | 批次号 |
| V_GROUP_CODE | — | 规则组编码 |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
