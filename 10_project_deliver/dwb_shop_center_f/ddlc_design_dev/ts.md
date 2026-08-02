# ETL 技术规格(TS)

> 目标表: `slshp.dwb_shop_center_f`(店铺中心宽表) - 生成 2026-08-02T18:57:44

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slshp.dwb_shop_center_f`(店铺中心宽表) |
| **I 视图** | `slshp.dwb_shop_center_i`(F表镜像) |
| **目标粒度** | 每行一个店铺记录 |
| **写入策略** | 全量调度 |
| **分布键** | shop_id |
| **字段统计** | 业务 16 + 审计 4 = 总计 20 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | dim.dim_shop_f | 店铺维度表 | dsf |
| 2 | dim.dim_region_f | 地区维度表 | drf |
| 3 | sdord.dwd_order_f | 订单明细事实表 | dof |
| 4 | sdrev.dwd_review_f | 评价事实表 | drf5 |

---

## 2. 表模型设计

- **F表**: `dwb_shop_center_f`(存数据)
- **I视图**: `dwb_shop_center_i`(F表镜像, 对外查询)
- **分布键**: shop_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 4 |
| 粒度变化 | 有 (dwd_order_f（订单明细粒度）与 dwd_review_f（评价明细粒度）需聚合到店铺粒度后再关联主表) |
| 多步骤加工字段 | 4 |
| 聚合后关联 | 否 |

**分段结论**: 不分段（用 CTE 内联聚合）
**理由**: JOIN 表数 4 与多步骤加工字段数 4 均未触及分段阈值（>12 / ≥5）； 订单聚合、评价聚合各自只在本规则内使用一次，无跨资产复用价值、无独立物理校验诉求， 按 design-guide §4.2 中间表 vs CTE 决策原则，采用 CTE 内联比建物理中间表更轻量； 单条 INSERT + 2 个 CTE 结构清晰，可读性与可维护性可控。


---

## 4. 规则详情

### R0001 - 店铺中心宽表加工

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_shop_center_f` |
| 设计意图 | 以 dim_shop_f 为主表（已是店铺粒度），LEFT JOIN dim_region_f 取省份名称； 订单明细 (dwd_order_f) 与评价明细 (dwd_review_f) 因粒度细于店铺，先经 CTE 按 shop_id 聚合收敛到店铺粒度后再 LEFT JOIN 回主表，一次性产出店铺级宽表。 采用 CTE 内联而非物理中间表，因聚合结果只在本规则内使用一次、无独立校验诉求。
 |
| 字段数 | 20 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dsf | main | 主表 dim_shop_f |
| drf | LEFT JOIN | dsf.province_code = drf.region_code |
| order_agg | LEFT JOIN | dsf.shop_id = order_agg.shop_id |
| review_agg | LEFT JOIN | dsf.shop_id = review_agg.shop_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_region_f | 是 | 无需对齐 |
| dwd_order_f | 否 | GROUP BY 收敛到 shop_id |
| dwd_review_f | 否 | GROUP BY 收敛到 shop_id |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 9 |
| aggregate | 7 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `shop_type_name`: 店铺类型中文化映射：FLAGSHIP→旗舰店，SPECIALTY→专卖店，FRANCHISE→专营店，其余取值→其他
- `shop_status_name`: 店铺状态中文化映射：OPEN→营业中，CLOSED→已关闭，FROZEN→冻结，其余取值→其他
- `open_days`: 营业天数 = 当前日期与开店时间(open_time)之间的天数差
- `total_order_cnt`: 按 shop_id 聚合 dwd_order_f，统计该店铺的累计订单行数
- `total_sales_amount`: 按 shop_id 汇总 dwd_order_f，对该店铺所有订单的支付金额(pay_amount)求和
- ...(共 11 个加工字段)

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
| 调度任务 | dwb_shop_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | slshp |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
