# ETL 技术规格(TS)

> 目标表: `slprd.dwb_product_center_f`(商品中心宽表) - 生成 2026-08-02T22:56:24

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slprd.dwb_product_center_f`(商品中心宽表) |
| **I 视图** | `slprd.dwb_product_center_i`(F表镜像) |
| **目标粒度** | 每行一个商品记录 |
| **写入策略** | 全量调度 |
| **分布键** | product_id |
| **字段统计** | 业务 35 + 审计 4 = 总计 39 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 3 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | dim.dim_product_f | 商品维度表 | dpf |
| 2 | dim.dim_product_category_f | 商品分类维度表 | dpc |
| 3 | dim.dim_brand_f | 品牌维度表 | dbf |
| 4 | dim.dim_shop_f | 店铺维度表 | dsf |
| 5 | sdinv.dwd_inventory_f | 库存事实表 | dif |
| 6 | sdord.dwd_order_detail_f | 订单商品明细事实表 | dod |
| 7 | sdrev.dwd_review_f | 评价事实表 | drf |

---

## 2. 表模型设计

- **F表**: `dwb_product_center_f`(存数据)
- **I视图**: `dwb_product_center_i`(F表镜像, 对外查询)
- **分布键**: product_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | dwb_product_sales_tmp1 | 一行=一个商品 | 把订单明细(多行/商品)按 product_id 聚合到商品粒度，产出销量/销售额/买家数/近30天销量，供 R0003 关联，避免主表行数发散 |
| R0002 | dwb_product_review_tmp1 | 一行=一个商品 | 把评价表(多行/商品)按 product_id 聚合到商品粒度，产出评价数/平均评分/好评率，供 R0003 关联，避免主表行数发散 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 7 |
| 粒度变化 | 有 (订单明细表、评价表为多行/商品，需先按 product_id 聚合到商品粒度再关联主表，否则商品行发散) |
| 多步骤加工字段 | 7 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 多步骤聚合字段=7(≥5 阈值)，且订单/评价表需先按 product_id 聚合后才能关联主表(聚合后关联)，单条 INSERT 难以保证正确与可校验；拆为销售汇总、评价汇总两个物理中间表收口，再由主规则 LEFT JOIN 装配目标宽表。中间表可独立校验且复用。

---

## 4. 规则详情

### R0001 - 商品销售汇总中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_product_sales_tmp1` |
| 设计意图 | 把订单明细(多行/商品)按 product_id 聚合到商品粒度，产出销量/销售额/买家数/近30天销量，供 R0003 关联，避免主表行数发散 |
| 字段数 | 4 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dod | main | 从 sdord.dwd_order_detail_f 读取 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_detail_f | 是 | GROUP BY product_id 收敛到商品粒度，聚合后 product_id 唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_sales_qty`: 按 product_id 汇总 dwd_order_detail_f 全量订单的 qty 求和，得到累计销量
- `total_sales_amount`: 按 product_id 汇总 dwd_order_detail_f 全量订单的 real_price×qty 求和，得到累计销售额
- `buyer_cnt`: 按 product_id 统计 dwd_order_detail_f 中去重 user_id 的数量，得到购买人数
- `sales_qty_30d`: 按 product_id 汇总 dwd_order_detail_f 近30天(以订单时间过滤)的 qty 求和，得到近30天销量

---

### R0002 - 商品评价汇总中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_product_review_tmp1` |
| 设计意图 | 把评价表(多行/商品)按 product_id 聚合到商品粒度，产出评价数/平均评分/好评率，供 R0003 关联，避免主表行数发散 |
| 字段数 | 3 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| drf | main | 从 sdrev.dwd_review_f 读取 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_review_f | 是 | GROUP BY product_id 收敛到商品粒度，聚合后 product_id 唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 3 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `review_cnt`: 按 product_id 统计 dwd_review_f 的评价总数 COUNT(*)
- `avg_rating`: 按 product_id 计算 dwd_review_f 的评分均值 AVG(rating)，保留一位小数
- `good_review_rate`: 按 product_id 统计 dwd_review_f 的好评数(评分达好评阈值)占比×100；好评率=好评数/评价总数×100

---

### R0003 - 商品中心宽表装配

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_product_center_f` |
| 设计意图 | 以 dim_product_f 为主表，LEFT JOIN 分类/品牌/店铺维度、库存快照及销售/评价汇总中间表，装配出每行一个商品的宽表(含价格折扣、库存状态等加工字段) |
| 字段数 | 32 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dpf | main | dim.dim_product_f 为主表 |
| dpc | LEFT JOIN | dpf.category_id = dpc.category_id |
| dbf | LEFT JOIN | dpf.brand_id = dbf.brand_id |
| dsf | LEFT JOIN | dpf.shop_id = dsf.shop_id |
| dif | LEFT JOIN | dpf.product_id = dif.product_id |
| sales_tmp | LEFT JOIN | dpf.product_id = sales_tmp.product_id |
| review_tmp | LEFT JOIN | dpf.product_id = review_tmp.product_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_product_category_f | 是 | category_id 维度表唯一 |
| dim_brand_f | 是 | brand_id 维度表唯一 |
| dim_shop_f | 是 | shop_id 维度表唯一 |
| dwd_inventory_f | 是 | 假定库存快照按 product_id 唯一(单仓/汇总)；若多仓多行需先按 product_id 聚合再关联 |
| dwb_product_sales_tmp1 | 是 | product_id 已在 R0001 GROUP BY 收敛唯一 |
| dwb_product_review_tmp1 | 是 | product_id 已在 R0002 GROUP BY 收敛唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 22 |
| aggregate | 6 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `product_status_name`: 将 dpf.product_status 枚举翻译为中文：ON_SHELF→上架、OFF_SHELF→下架、SOLD_OUT→售罄、其余→其他
- `discount_rate`: (market_price - sale_price) / market_price × 100，市场价相对销售价的折扣比率(%)
- `gross_profit`: sale_price - cost_price，单品毛利
- `gross_profit_rate`: (sale_price - cost_price) / sale_price × 100，毛利率(%)
- `available_qty`: stock_qty - locked_qty，可售数量
- ...(共 10 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0003 | dwb_product_sales_tmp1 |
| R0002 | R0003 | dwb_product_review_tmp1 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002 |
| 2 | R0003 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_product_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | slprd_dwb_daily |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
