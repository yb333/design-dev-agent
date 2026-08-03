# ETL 技术规格(TS)

> 目标表: `slprd.dwb_product_center_f`(商品中心宽表) - 生成 2026-08-03T23:02:39

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
| R0001 | dwb_product_center_tmp1 | 一行=一个商品的销售汇总 | 从订单商品明细表按商品ID聚合销售指标，产出中间表供主规则关联。 订单明细粒度（一行=一条明细）细于商品粒度，直接JOIN会导致行数发散， 需先聚合收敛为商品粒度。 |
| R0002 | dwb_product_center_tmp2 | 一行=一个商品的评价汇总 | 从评价事实表按商品ID聚合评价指标，产出中间表供主规则关联。 评价粒度（一行=一条评价）细于商品粒度，直接JOIN会导致行数发散， 需先聚合收敛为商品粒度。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 6 |
| 粒度变化 | 有 (订单明细表/评价表粒度细于商品粒度，在中间表 R0001/R0002 中按 product_id GROUP BY 收敛；R0003 主规则本身无粒度变化) |
| 多步骤加工字段 | 7 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 多步骤加工字段=7（≥5阈值），且订单明细/评价表粒度细于商品粒度需先聚合后关联。 拆为3个规则：R0001订单销售聚合中间表、R0002评价聚合中间表（可并行）， R0003主宽表关联（依赖R0001/R0002）。聚合逻辑独立于关联逻辑，中间表可独立校验。

---

## 4. 规则详情

### R0001 - 订单销售汇总

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_product_center_tmp1` |
| 设计意图 | 从订单商品明细表按商品ID聚合销售指标，产出中间表供主规则关联。 订单明细粒度（一行=一条明细）细于商品粒度，直接JOIN会导致行数发散， 需先聚合收敛为商品粒度。 |
| 字段数 | 4 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dod | main | 从 dwd_order_detail_f 读取全部订单明细数据 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_detail_f | 否 | GROUP BY product_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_sales_qty`: 从订单明细表按商品ID汇总累计销售数量，SUM(qty)
- `total_sales_amount`: 从订单明细表按商品ID汇总累计销售额，SUM(real_price * qty)
- `buyer_cnt`: 从订单明细表按商品ID统计去重购买用户数，COUNT(DISTINCT user_id)
- `sales_qty_30d`: 从订单明细表按商品ID统计近30天销售数量，限定订单时间在当前日期前30天内，SUM(qty)

---

### R0002 - 评价汇总

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_product_center_tmp2` |
| 设计意图 | 从评价事实表按商品ID聚合评价指标，产出中间表供主规则关联。 评价粒度（一行=一条评价）细于商品粒度，直接JOIN会导致行数发散， 需先聚合收敛为商品粒度。 |
| 字段数 | 3 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| drf | main | 从 dwd_review_f 读取全部评价数据 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_review_f | 否 | GROUP BY product_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 3 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `review_cnt`: 从评价表按商品ID统计评价总数，COUNT(*)
- `avg_rating`: 从评价表按商品ID计算平均评分，AVG(rating)
- `good_review_rate`: 从评价表按商品ID计算好评率，好评数（rating >= 4 的行数）/ 总评价数 * 100

---

### R0003 - 商品中心宽表加工

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_product_center_f` |
| 设计意图 | 以商品维度表为主表，LEFT JOIN 分类/品牌/店铺维度表补全属性， LEFT JOIN 库存表取库存指标，LEFT JOIN 订单销售聚合中间表(R0001)和 评价聚合中间表(R0002)取汇总指标，计算价格/库存衍生字段， 产出商品中心宽表（每行一个商品）。 |
| 字段数 | 32 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dpf | main | dim_product_f 为主表，粒度锚点：商品 |
| dpc | LEFT JOIN | dpf.category_id = dpc.category_id |
| dbf | LEFT JOIN | dpf.brand_id = dbf.brand_id |
| dsf | LEFT JOIN | dpf.shop_id = dsf.shop_id |
| dif | LEFT JOIN | dpf.product_id = dif.product_id |
| dwb_product_center_tmp1 | LEFT JOIN | dpf.product_id = tmp1.product_id |
| dwb_product_center_tmp2 | LEFT JOIN | dpf.product_id = tmp2.product_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_product_f | 是 | 直接关联 |
| dim_product_category_f | 是 | 直接关联 |
| dim_brand_f | 是 | 直接关联 |
| dim_shop_f | 是 | 直接关联 |
| dwd_inventory_f | 是 | 直接关联 |
| dwb_product_center_tmp1 | 是 | 直接关联 |
| dwb_product_center_tmp2 | 是 | 直接关联 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 22 |
| aggregate | 6 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `product_status_name`: 商品状态编码翻译为中文：ON_SHELF→上架、OFF_SHELF→下架、SOLD_OUT→售罄、其他值→其他
- `discount_rate`: 折扣率=(市场价-销售价)/市场价*100
- `gross_profit`: 单品毛利=销售价-成本价
- `gross_profit_rate`: 毛利率=(销售价-成本价)/销售价*100
- `available_qty`: 可售数量=库存数量-锁定数量
- ...(共 10 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0003 | dwb_product_center_tmp1 |
| R0002 | R0003 | dwb_product_center_tmp2 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002 |
| 2 | R0003 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | task_dwb_product_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | - |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
