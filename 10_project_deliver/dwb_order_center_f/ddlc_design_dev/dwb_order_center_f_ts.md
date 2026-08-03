# ETL 技术规格(TS)

> 目标表: `slord.dwb_order_center_f`(订单中心宽表) - 生成 2026-08-03T23:17:01

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
| R0001 | dwb_order_center_user_tmp1 | 一行=一个用户 | 收口所有按 user_id 聚合的用户画像/历史指标(先聚合再关联)，输出用户粒度，避免直接关联订单发散订单粒度。 |
| R0002 | dwb_order_center_prod_tmp1 | 一行=一个商品 | 收口按 product_id 聚合的商品累计销量/销售额(先聚合再关联)，输出商品粒度，避免发散订单粒度。 |
| R0003 | dwb_order_center_shop_tmp1 | 一行=一个店铺 | 收口按 shop_id 聚合的店铺历史订单数(先聚合再关联)，输出店铺粒度，避免发散订单粒度。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 18 |
| 粒度变化 | 有 (三类画像聚合(用户/商品/店铺)将订单粒度收敛为各自粒度后关联回订单；五张一对多事实表(明细/支付/物流/优惠券/退款)需收敛到订单粒度) |
| 多步骤加工字段 | 16 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: JOIN 表数量 18(有效关联操作约 24，dim_region_f 需 5 次别名关联、dim_product_category_f 需 3 次自关联)远超阈值 12；16 个多步骤加工字段需先聚合再关联；存在用户/商品/店铺三类粒度变化及五处一对多收敛。拆为 3 个画像中间表收口聚合，最终 F 表只做关联拼接，降低单条 INSERT 复杂度并使画像可独立校验。

---

## 4. 规则详情

### R0001 - 用户画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_order_center_user_tmp1` |
| 设计意图 | 收口所有按 user_id 聚合的用户画像/历史指标(先聚合再关联)，输出用户粒度，避免直接关联订单发散订单粒度。 |
| 字段数 | 13 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 按 user_id 分组的聚合基表 |
| dpf | LEFT JOIN | dof.user_id = dpf.user_id(聚合 fav_pay_method) |
| dcu | LEFT JOIN | dof.user_id = dcu.user_id(聚合 user_coupon_used_cnt) |
| drf17 | LEFT JOIN | dof.user_id = drf17.user_id(聚合 user_refund_cnt) |
| daf | LEFT JOIN | dof.activity_id = daf.activity_id(取活动类型用于偏好统计) |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dof | 是 | GROUP BY user_id 收敛到用户粒度，确保 user_id 唯一 |
| dpf | 否 | 按 user_id 分组取众数收敛 |
| dcu | 否 | 按 user_id 分组 COUNT 去重收敛 |
| drf17 | 否 | 按 user_id 分组 COUNT 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 12 |
| direct | 1 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `first_order_time`: 用户首次下单时间：对 dwd_order_f 按 user_id 分组，取该用户最早的 create_time
- `last_order_time`: 用户最近下单时间：对 dwd_order_f 按 user_id 分组，取该用户最新的 create_time
- `history_order_cnt`: 用户历史订单总数：对 dwd_order_f 按 user_id 分组统计订单条数
- `history_pay_amount`: 用户历史消费总额：对 dwd_order_f 按 user_id 分组，累加各订单 pay_amount
- `history_discount_amount`: 用户历史优惠总额：对 dwd_order_f 按 user_id 分组，累加各订单 discount_amount
- ...(共 12 个加工字段)

---

### R0002 - 商品画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_order_center_prod_tmp1` |
| 设计意图 | 收口按 product_id 聚合的商品累计销量/销售额(先聚合再关联)，输出商品粒度，避免发散订单粒度。 |
| 字段数 | 3 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dod | main | 按 product_id 分组的聚合基表 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dod | 是 | GROUP BY product_id 收敛到商品粒度，确保 product_id 唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 2 |
| direct | 1 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `product_sales_cnt`: 商品累计销量：对 dwd_order_detail_f 按 product_id 分组，累加各明细的 qty
- `product_sales_amount`: 商品累计销售额：对 dwd_order_detail_f 按 product_id 分组，累加各明细的 real_price 乘以 qty

---

### R0003 - 店铺画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 3 |
| 产出表 | `dwb_order_center_shop_tmp1` |
| 设计意图 | 收口按 shop_id 聚合的店铺历史订单数(先聚合再关联)，输出店铺粒度，避免发散订单粒度。 |
| 字段数 | 2 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 按 shop_id 分组的聚合基表 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dof | 是 | GROUP BY shop_id 收敛到店铺粒度，确保 shop_id 唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 1 |
| aggregate | 1 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `shop_history_order_cnt`: 店铺历史订单数：对 dwd_order_f 按 shop_id 分组 COUNT 订单数

---

### R0004 - 订单中心宽表F表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 4 |
| 产出表 | `dwb_order_center_f` |
| 设计意图 | 最终宽表：以订单事实表为主表，LEFT JOIN 三个画像中间表(用户/商品/店铺)及全部维表，做关联拼接与字段映射，产出订单粒度宽表。画像聚合已由 R0001-R0003 收口，本规则只做关联拼接。 |
| 字段数 | 132 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 订单主事实表 |
| main_product(CTE) | LEFT JOIN | dof.order_id = main_product.order_id |
| latest_payment(CTE) | LEFT JOIN | dof.order_id = latest_payment.order_id |
| latest_logistics(CTE) | LEFT JOIN | dof.order_id = latest_logistics.order_id |
| latest_coupon(CTE) | LEFT JOIN | dof.order_id = latest_coupon.order_id |
| latest_refund(CTE) | LEFT JOIN | dof.order_id = latest_refund.order_id |
| dwb_order_center_user_tmp1 | LEFT JOIN | dof.user_id = dwb_order_center_user_tmp1.user_id |
| dwb_order_center_prod_tmp1 | LEFT JOIN | main_product.product_id = dwb_order_center_prod_tmp1.product_id |
| dwb_order_center_shop_tmp1 | LEFT JOIN | dof.shop_id = dwb_order_center_shop_tmp1.shop_id |
| duf | LEFT JOIN | dof.user_id = duf.user_id |
| dul | LEFT JOIN | duf.level_id = dul.level_id |
| dpf7 | LEFT JOIN | main_product.product_id = dpf7.product_id |
| dpc | LEFT JOIN | dpf7.category_id = dpc.category_id(一级类目)；再按 parent_id 两次自关联取二/三级类目 |
| dbf | LEFT JOIN | dpf7.brand_id = dbf.brand_id |
| dsf | LEFT JOIN | dof.shop_id = dsf.shop_id |
| drf(收货省) | LEFT JOIN | dof.province_code = drf1.region_code |
| drf(收货市) | LEFT JOIN | dof.city_code = drf2.region_code |
| drf(收货区) | LEFT JOIN | dof.district_code = drf3.region_code |
| drf(店铺省) | LEFT JOIN | dsf.province_code = drf4.region_code |
| drf(店铺市) | LEFT JOIN | dsf.city_code = drf5.region_code |
| dpm | LEFT JOIN | latest_payment.pay_method = dpm.method_code |
| dlc | LEFT JOIN | latest_logistics.logistics_company = dlc.company_code |
| dwf | LEFT JOIN | latest_logistics.warehouse_id = dwf.warehouse_id |
| dcf | LEFT JOIN | latest_coupon.coupon_id = dcf.coupon_id |
| daf | LEFT JOIN | dof.activity_id = daf.activity_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dod(main_product CTE) | 否 | ROW_NUMBER 按 order_id 分区取第一条商品收敛 |
| dpf(latest_payment CTE) | 否 | 取支付成功中最新一条收敛 |
| dlf(latest_logistics CTE) | 否 | 取最新一条物流记录收敛 |
| dcu(latest_coupon CTE) | 否 | 取使用状态为 USED 的一张收敛 |
| drf17(latest_refund CTE) | 否 | 取退款成功的一笔收敛 |
| dwb_order_center_user_tmp1 | 是 | 无需额外收敛 |
| dwb_order_center_prod_tmp1 | 是 | 无需额外收敛 |
| dwb_order_center_shop_tmp1 | 是 | 无需额外收敛 |
| duf | 是 | 取当前有效用户 |
| dpf7 | 是 | 取当前有效商品 |
| dsf | 是 | 取当前有效店铺 |
| drf(地区维表多别名) | 是 | 按各自 region_code 关联，同一地区维表通过不同别名分别关联省/市/区 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 87 |
| aggregate | 41 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `order_status_name`: 订单状态名称：按 order_status 映射中文，PAID→已支付、SHIPPED→已发货、RECEIVED→已签收、CANCELLED→已取消，其余→其他
- `order_source_name`: 订单来源：按 order_source 映射，APP→APP端、WEB→网页端、MINIAPP→小程序、H5→H5页面，其余→其他
- `order_type_name`: 订单类型：按 order_type 映射，NORMAL→普通订单、PRESALE→预售订单、GROUPBUY→团购订单、SECKILL→秒杀订单，其余→其他
- `order_date`: 下单日期：取 create_time 的日期部分
- `receiver_phone_masked`: 收货人手机脱敏：保留前 3 位和后 4 位，中间用 **** 替换
- ...(共 45 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0004 | dwb_order_center_user_tmp1 |
| R0002 | R0004 | dwb_order_center_prod_tmp1 |
| R0003 | R0004 | dwb_order_center_shop_tmp1 |

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
| 任务组 | dwb_order_center |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
