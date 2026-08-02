# ETL 技术规格(TS)

> 目标表: `slord.dwb_order_center_f`(订单中心宽表) - 生成 2026-08-02T23:14:47

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slord.dwb_order_center_f`(订单中心宽表) |
| **I 视图** | `slord.dwb_order_center_i`(F表镜像) |
| **目标粒度** | 每行一个订单 |
| **写入策略** | 全量调度 |
| **分布键** | order_id |
| **字段统计** | 业务 146 + 审计 4 = 总计 150 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 4 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | sdord.dwd_order_f | 订单明细事实表 | dof |
| 2 | sdord.dwd_order_detail_f | 订单商品明细事实表 | dod |
| 3 | sdpay.dwd_payment_f | 支付事实表 | dpf |
| 4 | sdlog.dwd_logistics_f | 物流事实表 | dlf |
| 5 | sdmar.dwd_coupon_use_f | 优惠券使用事实表 | dcu |
| 6 | dim.dim_user_f | 用户维度表 | duf |
| 7 | dim.dim_user_level_f | 用户等级维度表 | dul |
| 8 | dim.dim_product_f | 商品维度表 | dpf7 |
| 9 | dim.dim_product_category_f | 商品分类维度表 | dpc |
| 10 | dim.dim_brand_f | 品牌维度表 | dbf |
| 11 | dim.dim_shop_f | 店铺维度表 | dsf |
| 12 | dim.dim_region_f | 地区维度表 | drf |
| 13 | dim.dim_warehouse_f | 仓库维度表 | dwf |
| 14 | dim.dim_payment_method_f | 支付方式维度表 | dpm |
| 15 | dim.dim_logistics_company_f | 物流公司维度表 | dlc |
| 16 | dim.dim_coupon_f | 优惠券维度表 | dcf |
| 17 | dim.dim_activity_f | 营销活动维度表 | daf |
| 18 | sdref.dwd_refund_f | 退款事实表 | drf17 |

---

## 2. 表模型设计

- **F表**: `dwb_order_center_f`(存数据)
- **I视图**: `dwb_order_center_i`(F表镜像, 对外查询)
- **分布键**: order_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | dwb_order_center_user_tmp1 | 一行=一个用户(user_id) | 收口所有按 user_id 聚合的用户级指标（历史订单统计、消费金额、RFM 分层、 常用支付方式、优惠券使用、退款次数、偏好活动类型等），避免在主 INSERT 中 混入聚合后关联逻辑。中间表粒度=一个用户一行，以 user_id 为关联键供主规则 JOIN。
 |
| R0002 | dwb_order_center_prod_tmp2 | 一行=一个商品(product_id) | 收口按 product_id 聚合的商品级累计销量与销售额指标。中间表粒度=一个商品一行， 以 product_id 为关联键供主规则 JOIN。
 |
| R0003 | dwb_order_center_shop_tmp3 | 一行=一个店铺(shop_id) | 收口按 shop_id 聚合的店铺历史订单数指标。中间表粒度=一个店铺一行， 以 shop_id 为关联键供主规则 JOIN。
 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 18 |
| 粒度变化 | 有 (用户画像按 user_id 聚合、商品画像按 product_id 聚合、店铺画像按 shop_id 聚合；主表粒度为订单(order_id)) |
| 多步骤加工字段 | 17 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 命中多个分段阈值：关联表数 18 > 12、多步骤加工字段 17 ≥ 5、存在用户/商品/店铺三类 聚合后关联、复杂关联链(商品类目三级、地区省市县)。需建物理中间表收口聚合逻辑， 避免单条 INSERT 过复杂且便于独立校验。


---

## 4. 规则详情

### R0001 - 用户画像聚合

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_order_center_user_tmp1` |
| 设计意图 | 收口所有按 user_id 聚合的用户级指标（历史订单统计、消费金额、RFM 分层、 常用支付方式、优惠券使用、退款次数、偏好活动类型等），避免在主 INSERT 中 混入聚合后关联逻辑。中间表粒度=一个用户一行，以 user_id 为关联键供主规则 JOIN。
 |
| 字段数 | 12 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | 聚合源 | GROUP BY user_id |
| dpf | 聚合源 | GROUP BY user_id |
| dcu | 聚合源 | GROUP BY user_id |
| drf17 | 聚合源 | GROUP BY user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f | 是 | GROUP BY user_id 收敛为每用户一行 |
| dwd_payment_f | 是 | GROUP BY user_id 收敛 |
| dwd_coupon_use_f | 是 | GROUP BY user_id 收敛 |
| dwd_refund_f | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 12 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `first_order_time`: 以 user_id 分组汇总 dwd_order_f 全部历史订单，取最早的下单时间作为首次下单时间
- `last_order_time`: 以 user_id 分组汇总 dwd_order_f 全部历史订单，取最近的下单时间作为最近下单时间
- `history_order_cnt`: 以 user_id 分组统计 dwd_order_f 历史订单总数
- `history_pay_amount`: 以 user_id 分组对 dwd_order_f 实付金额求和，得到历史消费总额
- `history_discount_amount`: 以 user_id 分组对 dwd_order_f 优惠金额求和，得到历史优惠总额
- ...(共 12 个加工字段)

---

### R0002 - 商品画像聚合

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_order_center_prod_tmp2` |
| 设计意图 | 收口按 product_id 聚合的商品级累计销量与销售额指标。中间表粒度=一个商品一行， 以 product_id 为关联键供主规则 JOIN。
 |
| 字段数 | 2 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dod | 聚合源 | GROUP BY product_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_detail_f | 是 | GROUP BY product_id 收敛为每商品一行 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 2 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `product_sales_cnt`: 以 product_id 分组汇总 dwd_order_detail_f，对购买数量求和得到商品累计销量
- `product_sales_amount`: 以 product_id 分组汇总 dwd_order_detail_f，对实付单价乘以数量求和得到商品累计销售额

---

### R0003 - 店铺画像聚合

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_order_center_shop_tmp3` |
| 设计意图 | 收口按 shop_id 聚合的店铺历史订单数指标。中间表粒度=一个店铺一行， 以 shop_id 为关联键供主规则 JOIN。
 |
| 字段数 | 1 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | 聚合源 | GROUP BY shop_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f | 是 | GROUP BY shop_id 收敛为每店铺一行 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 1 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `shop_history_order_cnt`: 以 shop_id 分组统计 dwd_order_f 历史订单总数

---

### R0004 - 订单中心宽表主组装

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_order_center_f` |
| 设计意图 | 以 dwd_order_f(订单主事实，order_id 粒度)为骨架，LEFT JOIN 订单明细(取第一条主商品)、 支付(取最新成功)、物流(取最新)、优惠券(取一条)、退款(取最新成功退款)及全部维度表， 并关联 R0001/R0002/R0003 三张画像中间表，一次性组装出订单中心宽表全部字段。 所有直取维度字段、码值翻译、脱敏、地址拼接、时长计算、订单级标识均在此规则产出。
 |
| 字段数 | 135 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 主事实骨架 |
| dod | LEFT JOIN | t.order_id=od.order_id |
| dpf | LEFT JOIN | t.order_id=pay.order_id |
| dlf | LEFT JOIN | t.order_id=log.order_id |
| dcu | LEFT JOIN | t.order_id=cu.order_id |
| drf17 | LEFT JOIN | t.order_id=rf.order_id |
| duf | LEFT JOIN | t.user_id=u.user_id |
| dul | LEFT JOIN | u.level_id=ul.level_id |
| dpf7 | LEFT JOIN | od.product_id=p.product_id |
| dpc | LEFT JOIN | p.category_id=pc.category_id(一级) → pc.parent_id=pc2.category_id(二级) → pc2.parent_id=pc3.category_id(三级) |
| dbf | LEFT JOIN | p.brand_id=b.brand_id |
| dsf | LEFT JOIN | t.shop_id=s.shop_id |
| drf | LEFT JOIN | t.province_code=r1.region_code(省) / t.city_code=r2.region_code(市) / t.district_code=r3.region_code(县) / s.province_code / s.city_code |
| dwf | LEFT JOIN | log.warehouse_id=wh.warehouse_id |
| dpm | LEFT JOIN | pay.pay_method=pm.method_code |
| dlc | LEFT JOIN | log.logistics_company=lc.company_code |
| dcf | LEFT JOIN | cu.coupon_id=c.coupon_id |
| daf | LEFT JOIN | t.activity_id=act.activity_id |
| dwb_order_center_user_tmp1 | LEFT JOIN | t.user_id=tmp1.user_id |
| dwb_order_center_prod_tmp2 | LEFT JOIN | od.product_id=tmp2.product_id |
| dwb_order_center_shop_tmp3 | LEFT JOIN | t.shop_id=tmp3.shop_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f | 是 |  |
| dwd_order_detail_f | 否 | ROW_NUMBER() OVER(PARTITION BY order_id ORDER BY ...) 取第一条商品作为主商品 |
| dwd_payment_f | 否 | ROW_NUMBER 取最新一条成功支付记录(pay_time 倒序) |
| dwd_logistics_f | 否 | ROW_NUMBER 取最新一条物流信息 |
| dwd_coupon_use_f | 否 | ROW_NUMBER 取第一条已使用优惠券记录 |
| dwd_refund_f | 否 | ROW_NUMBER 取最新一条成功退款记录 |
| dim_user_f | 是 |  |
| dim_user_level_f | 是 |  |
| dim_product_f | 是 |  |
| dim_product_category_f | 是 |  |
| dim_brand_f | 是 |  |
| dim_shop_f | 是 |  |
| dim_region_f | 是 |  |
| dim_warehouse_f | 是 |  |
| dim_payment_method_f | 是 |  |
| dim_logistics_company_f | 是 |  |
| dim_coupon_f | 是 |  |
| dim_activity_f | 是 |  |
| dwb_order_center_user_tmp1 | 是 |  |
| dwb_order_center_prod_tmp2 | 是 |  |
| dwb_order_center_shop_tmp3 | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 90 |
| aggregate | 41 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `order_status_name`: 订单状态码翻译为中文：PAID-已支付/SHIPPED-已发货/RECEIVED-已签收/CANCELLED-已取消/其他
- `order_date`: 下单时间截取到日期
- `order_source_name`: 订单来源码翻译为中文：APP-APP端/WEB-网页端/MINIAPP-小程序/H5-H5页面/其他
- `order_type_name`: 订单类型码翻译为中文：NORMAL-普通订单/PRESALE-预售订单/GROUPBUY-团购订单/SECKILL-秒杀订单/其他
- `delivery_days`: 签收时间减去发货时间，得到物流在途天数
- ...(共 45 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0004 | dwb_order_center_user_tmp1 |
| R0002 | R0004 | dwb_order_center_prod_tmp2 |
| R0003 | R0004 | dwb_order_center_shop_tmp3 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002, R0003 |
| 2 | R0004 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_order_center_f_load |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | - |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
