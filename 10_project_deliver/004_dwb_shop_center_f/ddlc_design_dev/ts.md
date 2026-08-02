# ETL 技术规格(TS)

> 目标表: `slshp.dwb_shop_center_f`(店铺中心宽表) - 生成 2026-08-02T22:44:15

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
| 粒度变化 | 无 (主表店铺粒度保持不变；订单/评价通过 CTE 预聚合到店铺粒度后关联，整体输出仍为店铺粒度) |
| 多步骤加工字段 | 4 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN 4表(<阈值12)、多步骤加工字段 4(<阈值5)、无粒度变化；订单/评价聚合用 CTE 内联即可收敛，单条 INSERT 可一次写对，无需物理中间表收口

---

## 4. 规则详情

### R0001 - 店铺中心宽表装配

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_shop_center_f` |
| 设计意图 | 以 dim_shop_f 为主表，LEFT JOIN 地区维度取省份名，并通过两个 CTE 把订单/评价事实表预聚合到店铺粒度后关联，一次产出店铺中心宽表全量字段 |
| 字段数 | 20 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dsf | main | dim_shop_f 主表，店铺粒度 |
| drf | LEFT JOIN | dsf.province_code = drf.region_code |
| order_agg | LEFT JOIN | dsf.shop_id = order_agg.shop_id |
| review_agg | LEFT JOIN | dsf.shop_id = review_agg.shop_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_region_f | 是 |  |
| dwd_order_f | 否 | GROUP BY 收敛（CTE order_agg 按 shop_id 聚合后再关联） |
| dwd_review_f | 否 | GROUP BY 收敛（CTE review_agg 按 shop_id 聚合后再关联） |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 9 |
| aggregate | 7 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `shop_type_name`: 店铺类型枚举翻译：FLAGSHIP→旗舰店，SPECIALTY→专卖店，FRANCHISE→专营店，其余→其他
- `shop_status_name`: 店铺状态枚举翻译：OPEN→营业中，CLOSED→已关闭，FROZEN→冻结，其余→其他
- `open_days`: 营业天数 = 当前日期减去开店时间的天数差
- `total_order_cnt`: 累计订单数：从订单明细事实表(dwd_order_f)按 shop_id 汇总订单行数 COUNT(*)
- `total_sales_amount`: 累计销售额：从订单明细事实表(dwd_order_f)按 shop_id 汇总实付金额 SUM
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
| 调度任务 | dwb_shop_center_f_load |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | slshp |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
