# ETL 技术规格(TS)

> 目标表: `dws.dwb_trade_wide_f`(交易宽表) - 生成 2026-08-02T18:50:22

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
| JOIN 表数量 | 4 |
| 粒度变化 | 有 (支付明细和物流明细为多行/订单，通过 CTE 预聚合（GROUP BY order_id）收敛到订单粒度) |
| 多步骤加工字段 | 2 |
| 聚合后关联 | 是 |

**分段结论**: 不分段
**理由**: JOIN 表数 4（远低于阈值 12），多步骤加工字段 2（低于阈值 5）， 复杂度中等偏低。支付/物流收敛用 CTE 内联——仅在本规则内使用一次、 无需独立校验，单条 INSERT 即可清晰表达全部加工逻辑。

---

## 4. 规则详情

### R0001 - 交易宽表全量加工

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_trade_wide_f` |
| 设计意图 | 以订单明细为主表，LEFT JOIN 客户维、商品维补维度属性， 通过 CTE 预聚合支付和物流（按 order_id 汇总收敛多行）， 一次性产出交易宽表 F 表。 |
| 字段数 | 15 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| o | main |  |
| c | LEFT JOIN | o.cust_id = c.cust_id |
| p | LEFT JOIN | o.product_id = p.product_id |
| pay_agg | LEFT JOIN | o.order_id = pay_agg.order_id |
| log_agg | LEFT JOIN | o.order_id = log_agg.order_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_cust_d (c) | 是 |  |
| dim_product_d (p) | 否 | 取最新有效行 |
| ods_payment_di (pay) | 否 | GROUP BY 收敛（CTE pay_agg 预聚合） |
| ods_logistics_di (log) | 否 | GROUP BY 收敛（CTE log_agg 预聚合） |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 9 |
| assign | 4 |
| aggregate | 2 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_pay_amt`: 按订单ID汇总支付明细表的支付金额（SUM），将一个订单的多笔支付收敛为一行
- `total_ship_fee`: 按订单ID汇总物流明细表的运费（SUM），将一个订单的多条物流收敛为一行
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
| 调度任务 | dwb_trade_wide_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | dwb_trade |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
