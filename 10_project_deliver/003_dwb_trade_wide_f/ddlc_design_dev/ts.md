# ETL 技术规格(TS)

> 目标表: `dws.dwb_trade_wide_f`(交易宽表) - 生成 2026-08-02T22:36:09

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `dws.dwb_trade_wide_f`(交易宽表) |
| **I 视图** | `dws.dwb_trade_wide_i`(F表镜像) |
| **目标粒度** | 每行一个订单 |
| **写入策略** | 全量调度 |
| **分布键** | order_id |
| **字段统计** | 业务 11 + 审计 4 = 总计 15 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | ods.ods_trade_order_di | 订单明细 | o |
| 2 | dwrdim.dim_cust_d | 客户维表 | c |
| 3 | dwrdim.dim_product_d | 商品维表 | p |
| 4 | ods.ods_payment_di | 支付明细 | pay |
| 5 | ods.ods_logistics_di | 物流明细 | log |

---

## 2. 表模型设计

- **F表**: `dwb_trade_wide_f`(存数据)
- **I视图**: `dwb_trade_wide_i`(F表镜像, 对外查询)
- **分布键**: order_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 5 |
| 粒度变化 | 无 (输入输出粒度一致，均一行=一个订单) |
| 多步骤加工字段 | 2 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN表数5<12、多步骤加工字段2<5、无粒度变化，复杂度未达分段阈值；pay/log收敛与商品维取最新行用CTE内联，无需物理中间表

---

## 4. 规则详情

### R0001 - 交易宽表全量装配

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_trade_wide_f` |
| 设计意图 | 5表JOIN宽表，复杂度未达分段阈值，pay/log收敛用CTE内联处理，商品维取最新有效行，单条INSERT直产目标F表 |
| 字段数 | 15 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| o | main |  |
| c | LEFT JOIN | o.cust_id = c.cust_id |
| p | LEFT JOIN | o.product_id = prod_latest.product_id |
| pay | LEFT JOIN | o.order_id = pay_agg.order_id |
| log | LEFT JOIN | o.order_id = log_agg.order_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| o | 是 |  |
| c | 是 |  |
| p | 否 | 取最新有效行 |
| pay | 否 | GROUP BY order_id 收敛 |
| log | 否 | GROUP BY order_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 9 |
| assign | 4 |
| aggregate | 2 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_pay_amt`: 按 order_id 汇总支付明细的支付金额(pay CTE 已按订单收敛)
- `total_ship_fee`: 按 order_id 汇总物流明细的运费(log CTE 已按订单收敛)
- `del_flag`: 固定赋值
- `crt_cycle_id`: 固定赋值
- `last_upd_cycle_id`: 固定赋值
- ...(共 6 个加工字段)

---

## 5. 数据流向

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dws_dwb_trade_wide_f_d |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | dwb_trade |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
