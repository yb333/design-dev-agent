# ETL 技术规格(TS)

> 目标表: `slusr.dwb_user_center_f`(用户中心宽表) - 生成 2026-08-02T19:05:28

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slusr.dwb_user_center_f`(用户中心宽表) |
| **I 视图** | `slusr.dwb_user_center_i`(F表镜像) |
| **目标粒度** | 每行一个用户记录 |
| **写入策略** | 全量调度 |
| **分布键** | user_id |
| **字段统计** | 业务 42 + 审计 4 = 总计 46 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 4 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | dim.dim_user_f | 用户维度表 | duf |
| 2 | dim.dim_user_level_f | 用户等级维度表 | dul |
| 3 | dim.dim_region_f | 地区维度表 | drf |
| 4 | dim.dim_user_source_f | 用户来源维度表 | dus |
| 5 | sdord.dwd_order_f | 订单明细事实表 | dof |
| 6 | sdlog.dwd_user_behavior_f | 用户行为事实表 | dub |
| 7 | sdmar.dwd_coupon_use_f | 优惠券使用事实表 | dcu |
| 8 | sdref.dwd_refund_f | 退款事实表 | drf9 |
| 9 | sdlog.dwd_cart_f | 购物车事实表 | dcf |

---

## 2. 表模型设计

- **F表**: `dwb_user_center_f`(存数据)
- **I视图**: `dwb_user_center_i`(F表镜像, 对外查询)
- **分布键**: user_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | dwb_user_order_tmp | 一行=一个用户 | 将订单明细事实表按用户聚合收口为用户粒度的订单画像，为最终宽表提供订单域指标及 RFM 打分的输入 |
| R0002 | dwb_user_behavior_tmp | 一行=一个用户 | 将用户行为事实表按用户聚合收口为用户粒度的行为画像，提供浏览/收藏/加购行为指标，支撑转化率派生计算 |
| R0003 | dwb_user_marketing_tmp | 一行=一个用户 | 将优惠券使用、退款、购物车三张事实表各自按用户聚合后合并为用户粒度的营销画像，收口营销域指标 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 8 |
| 粒度变化 | 有 (5 个事实表（订单/行为/优惠券/退款/购物车）均为明细粒度，需先按 user_id 聚合收口到用户粒度后再关联到用户主表（聚合后关联）) |
| 多步骤加工字段 | 22 |
| 聚合后关联 | 否 |

**分段结论**: 分段
**理由**: 多项复杂度指标触发分段：(1) 5 个事实表需按 user_id 聚合收口（粒度变化+聚合后关联）；(2) 多步骤加工字段 22 个（远超阈值 5）：含 5 订单聚合+3 行为聚合+5 营销聚合+4 RFM 打分+5 派生比率/标签；(3) JOIN 表 8 张（4 dim + region 二次关联 + 3 画像中间表）。采用分段策略：将 5 个事实表的聚合收口为 3 个用户画像物理中间表（订单/行为/营销），最终在目标F表规则中组装 dim 直取字段+单步加工+派生计算+RFM 跨全量打分+审计字段。中间表可独立校验、语义清晰、被 RFM 复用，故建物理中间表而非 CTE。

---

## 4. 规则详情

### R0001 - 订单画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | 用户中心 |
| 执行序 | 1 |
| 产出表 | `dwb_user_order_tmp` |
| 设计意图 | 将订单明细事实表按用户聚合收口为用户粒度的订单画像，为最终宽表提供订单域指标及 RFM 打分的输入 |
| 字段数 | 4 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 单源表聚合，无关联 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f (dof) | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_order_cnt`: 从订单明细事实表按用户分组，统计历史订单总数，仅计入未取消、未删除的订单
- `total_pay_amount`: 按用户分组对支付金额求和，得到历史总消费金额，仅计入未取消、未删除的订单
- `last_order_time`: 按用户分组取订单创建时间的最大值作为最近下单时间
- `first_order_time`: 按用户分组取订单创建时间的最小值作为首次下单时间

---

### R0002 - 行为画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | 用户中心 |
| 执行序 | 2 |
| 产出表 | `dwb_user_behavior_tmp` |
| 设计意图 | 将用户行为事实表按用户聚合收口为用户粒度的行为画像，提供浏览/收藏/加购行为指标，支撑转化率派生计算 |
| 字段数 | 3 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dub | main | 单源表聚合，无关联 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_user_behavior_f (dub) | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 3 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_pv_cnt`: 从用户行为事实表按用户分组，对浏览次数求和
- `total_collect_cnt`: 按用户分组对收藏次数求和
- `total_cart_cnt`: 按用户分组对加购次数求和

---

### R0003 - 营销画像中间表

| 项目 | 内容 |
|------|------|
| 场景 | 用户中心 |
| 执行序 | 3 |
| 产出表 | `dwb_user_marketing_tmp` |
| 设计意图 | 将优惠券使用、退款、购物车三张事实表各自按用户聚合后合并为用户粒度的营销画像，收口营销域指标 |
| 字段数 | 5 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dcu | main | 优惠券子聚合：按 user_id 分组 |
| drf9 | LEFT JOIN | 退款子聚合按 user_id 关联合并 |
| dcf | LEFT JOIN | 购物车子聚合按 user_id 关联合并 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_coupon_use_f (dcu) | 是 | GROUP BY user_id 收敛 |
| dwd_refund_f (drf9) | 是 | GROUP BY user_id 收敛 |
| dwd_cart_f (dcf) | 是 | GROUP BY user_id 收敛（限定 del_flag='N'） |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 5 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `coupon_used_cnt`: 从优惠券使用事实表按用户分组，统计优惠券使用记录数
- `coupon_total_amount`: 按用户分组对优惠券抵扣金额求和
- `refund_cnt`: 从退款事实表按用户分组，统计退款记录数
- `cart_product_cnt`: 从购物车事实表按用户分组（仅未删除的购物车记录），统计商品件数
- `cart_total_amount`: 按用户分组（仅未删除的购物车记录），对商品数量乘以单价求和得到购物车金额

---

### R0004 - 用户中心宽表组装

| 项目 | 内容 |
|------|------|
| 场景 | 用户中心 |
| 执行序 | 4 |
| 产出表 | `dwb_user_center_f` |
| 设计意图 | 以用户维度为主表，关联等级/地区/来源维度及三张画像中间表，装配全部用户中心宽表字段（直取+加工+派生+RFM打分+审计） |
| 字段数 | 34 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| duf | main | 用户维度主表 |
| dul | LEFT JOIN | duf.level_id = dul.level_id |
| drf | LEFT JOIN | duf.province_code = drf.region_code（地区表第一次关联：取省份名称） |
| drf | LEFT JOIN | duf.city_code = drf.region_code（地区表第二次关联：取城市名称，需为同表起不同别名） |
| dus | LEFT JOIN | duf.source_id = dus.source_id |
| dwb_user_order_tmp | LEFT JOIN | duf.user_id = dwb_user_order_tmp.user_id |
| dwb_user_behavior_tmp | LEFT JOIN | duf.user_id = dwb_user_behavior_tmp.user_id |
| dwb_user_marketing_tmp | LEFT JOIN | duf.user_id = dwb_user_marketing_tmp.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_user_f (duf) | 是 | 无需对齐 |
| dim_user_level_f (dul) | 是 | 无需对齐 |
| dim_region_f (drf) - 省份关联 | 是 | 无需对齐 |
| dim_region_f (drf) - 城市关联 | 是 | 无需对齐 |
| dim_user_source_f (dus) | 是 | 无需对齐 |
| dwb_user_order_tmp | 是 | 已 GROUP BY 收敛 |
| dwb_user_behavior_tmp | 是 | 已 GROUP BY 收敛 |
| dwb_user_marketing_tmp | 是 | 已 GROUP BY 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 16 |
| direct | 14 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `user_phone_masked`: 对手机号脱敏，保留前3位和后4位，中间用4个星号替代
- `gender_name`: 性别编码字典翻译：M转男、F转女、其他为未知
- `age`: 用当前日期的年份减去出生日期的年份，得到年龄
- `register_days`: 计算注册时间距今的天数
- `user_status_name`: 用户状态编码字典翻译：ACTIVE转正常、INACTIVE转未激活、FROZEN转冻结、其他为其他
- ...(共 20 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0004 | dwb_user_order_tmp |
| R0002 | R0004 | dwb_user_behavior_tmp |
| R0003 | R0004 | dwb_user_marketing_tmp |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002, R0003 |
| 2 | R0004 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_user_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | dwb_user_center |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
