# ETL 技术规格(TS)

> 目标表: `slmar.dwb_marketing_center_f`(营销中心宽表) - 生成 2026-08-03T22:53:58

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slmar.dwb_marketing_center_f`(营销中心宽表) |
| **I 视图** | `slmar.dwb_marketing_center_i`(F表镜像) |
| **目标粒度** | 每行一个营销记录 |
| **写入策略** | 全量调度 |
| **分布键** | activity_id |
| **字段统计** | 业务 25 + 审计 4 = 总计 29 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | sdmar.dwd_activity_f | 活动事实表 | daf |
| 2 | dim.dim_activity_type_f | 活动类型维度表 | dat |
| 3 | dim.dim_coupon_f | 优惠券维度表 | dcf |
| 4 | sdmar.dwd_coupon_use_f | 优惠券使用事实表 | dcu |
| 5 | sdord.dwd_order_f | 订单明细事实表 | dof |

---

## 2. 表模型设计

- **F表**: `dwb_marketing_center_f`(存数据)
- **I视图**: `dwb_marketing_center_i`(F表镜像, 对外查询)
- **分布键**: activity_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | slmar.dwb_marketing_center_f | 一行=一个营销记录（活动粒度） | 主查询：以活动事实表(dwd_activity_f)为粒度锚点，LEFT JOIN 活动类型维度表取类型说明、 LEFT JOIN 优惠券维度表取券信息，并 LEFT JOIN 订单指标 CTE(order_agg，由 dwd_order_f 按 activity_id 预聚合得到订单数/GMV/参与人数/优惠金额/新客订单数)取活动级订单指标， 最后在主查询层计算派生比率(优惠券使用率/人均消费/新客占比/活动ROI)，按活动粒度全量覆盖写入宽表。 订单明细经 CTE 收敛后再关联，避免活动行发散。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 3 |
| 粒度变化 | 有 (订单明细(dwd_order_f，订单粒度)→活动粒度，经 CTE order_agg 预聚合收敛后关联；主表活动粒度不变。) |
| 多步骤加工字段 | 6 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN≤12（3）、订单指标经 CTE order_agg 预聚合后关联（聚合后关联=否）；多步骤加工字段虽达 6 个， 但均源自同一订单聚合 CTE（单步收敛即可完成），满足 CTE 内联条件，不建物理中间表。

---

## 4. 规则详情

### R0001 - 营销中心宽表写入

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `slmar.dwb_marketing_center_f` |
| 设计意图 | 主查询：以活动事实表(dwd_activity_f)为粒度锚点，LEFT JOIN 活动类型维度表取类型说明、 LEFT JOIN 优惠券维度表取券信息，并 LEFT JOIN 订单指标 CTE(order_agg，由 dwd_order_f 按 activity_id 预聚合得到订单数/GMV/参与人数/优惠金额/新客订单数)取活动级订单指标， 最后在主查询层计算派生比率(优惠券使用率/人均消费/新客占比/活动ROI)，按活动粒度全量覆盖写入宽表。 订单明细经 CTE 收敛后再关联，避免活动行发散。 |
| 字段数 | 29 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| daf | main | 主表（粒度锚点：每行一个活动，activity_id 唯一） |
| dat | LEFT JOIN | daf.activity_type = dat.type_code |
| dcf | LEFT JOIN | daf.activity_id = dcf.activity_id |
| order_agg | LEFT JOIN | daf.activity_id = order_agg.activity_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_activity_type_f | 是 | 直接关联 |
| dim_coupon_f | 否 | 需确认收敛策略（假设每活动一券；若一对多需取主券或聚合） |
| dwd_order_f | 否 | CTE 预聚合收敛（按 activity_id GROUP BY 后关联） |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 13 |
| aggregate | 12 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `activity_type_name`: 活动类型编码转中文：SECKILL→秒杀、GROUPBUY→团购、PRESALE→预售、FULL_REDUCE→满减、 FULL_GIFT→满赠，其余→其他。
- `activity_status_name`: 活动状态编码转中文：DRAFT→草稿、PENDING→待开始、RUNNING→进行中、ENDED→已结束， 其余→其他。
- `activity_days`: 活动天数 = 结束时间与开始时间的天数差。
- `coupon_type_name`: 优惠券类型编码转中文：FULL_REDUCE→满减券、DISCOUNT→折扣券、CASH→现金券，其余→其他。
- `coupon_use_rate`: 优惠券使用率 = 已使用量 / 发放总量 × 100，发放总量为 0 时返回 NULL 避免除零。
- ...(共 16 个加工字段)

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
| 调度任务 | task_dwb_marketing_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | GROUP_SLMAR |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
