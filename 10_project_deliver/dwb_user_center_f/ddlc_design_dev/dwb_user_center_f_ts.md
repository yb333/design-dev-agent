# ETL 技术规格(TS)

> 目标表: `slusr.dwb_user_center_f`(用户中心宽表) - 生成 2026-08-03T23:03:50

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
| 8 | sdref.dwd_refund_f | 退款事实表 | drf7 |
| 9 | sdlog.dwd_cart_f | 购物车事实表 | dcf |

---

## 2. 表模型设计

- **F表**: `dwb_user_center_f`(存数据)
- **I视图**: `dwb_user_center_i`(F表镜像, 对外查询)
- **分布键**: user_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | dwb_user_center_tmp1 | 一行=一个用户 | 以 dim_user_f 为主表，LEFT JOIN 等级/地区/来源维度，产出用户基础属性宽表，供最终装配规则引用。粒度不变（一行一用户）。 |
| R0002 | dwb_user_center_tmp2 | 一行=一个用户 | 对 dwd_order_f 排除作废/删除订单后按 user_id 聚合，产出用户级订单汇总指标，供最终装配规则引用。粒度从订单明细收敛到用户。 |
| R0003 | dwb_user_center_tmp3 | 一行=一个用户 | 对 dwd_user_behavior_f 按 user_id 聚合浏览/收藏/加购行为指标，供最终装配规则引用。粒度从行为明细收敛到用户。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 6 |
| 粒度变化 | 有 (dwd_order_f / dwd_user_behavior_f / dwd_coupon_use_f / dwd_refund_f / dwd_cart_f 五个事实表从多行明细聚合到一行一用户粒度) |
| 多步骤加工字段 | 16 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 5 个事实表需先按 user_id GROUP BY 聚合后才能关联用户维度（直接 JOIN 会导致笛卡尔发散）；16 个多步骤加工字段远超阈值 5；RFM 评分需在全量用户上做 NTILE(5) 窗口函数。拆 3 个物理中间表（tmp1 基础属性 / tmp2 订单汇总 / tmp3 行为汇总）+ 1 个最终装配规则（优惠券/退款/购物车用 CTE 内联）。

---

## 4. 规则详情

### R0001 - 用户基础属性中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_user_center_tmp1` |
| 设计意图 | 以 dim_user_f 为主表，LEFT JOIN 等级/地区/来源维度，产出用户基础属性宽表，供最终装配规则引用。粒度不变（一行一用户）。 |
| 字段数 | 20 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| duf | main |  |
| dul | LEFT JOIN | duf.level_id = dul.level_id |
| drf | LEFT JOIN | duf.province_code = drf.region_code |
| drf_city | LEFT JOIN | duf.city_code = drf_city.region_code |
| dus | LEFT JOIN | duf.source_id = dus.source_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_user_level_f | 是 |  |
| dim_region_f (province) | 是 |  |
| dim_region_f (city) | 是 |  |
| dim_user_source_f | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 14 |
| aggregate | 6 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `user_phone_masked`: 手机号脱敏：取前3位拼接'****'再拼接后4位
- `gender_name`: 性别代码转中文：M→男，F→女，其余→未知
- `age`: 年龄：当前年份减去出生年份（YEAR(CURDATE()) - YEAR(birthday)）
- `register_days`: 注册天数：当前日期减去注册日期的天数差
- `city_name`: 通过 city_code 二次关联 dim_region_f 获取城市名称（省份已通过 province_code 关联，城市需用 city_code 再 JOIN 一次 dim_region_f）
- ...(共 6 个加工字段)

---

### R0002 - 订单汇总中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_user_center_tmp2` |
| 设计意图 | 对 dwd_order_f 排除作废/删除订单后按 user_id 聚合，产出用户级订单汇总指标，供最终装配规则引用。粒度从订单明细收敛到用户。 |
| 字段数 | 4 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main |  |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_order_cnt`: 排除 CANCELLED/DELETED 状态订单后，按 user_id 统计历史订单数 COUNT(*)
- `total_pay_amount`: 排除 CANCELLED/DELETED 状态订单后，按 user_id 汇总支付金额 SUM(pay_amount)
- `last_order_time`: 排除 CANCELLED/DELETED 状态订单后，按 user_id 取最大下单时间 MAX(create_time)
- `first_order_time`: 排除 CANCELLED/DELETED 状态订单后，按 user_id 取最小下单时间 MIN(create_time)

---

### R0003 - 行为汇总中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_user_center_tmp3` |
| 设计意图 | 对 dwd_user_behavior_f 按 user_id 聚合浏览/收藏/加购行为指标，供最终装配规则引用。粒度从行为明细收敛到用户。 |
| 字段数 | 3 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dub | main |  |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_user_behavior_f | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 3 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_pv_cnt`: 按 user_id 汇总浏览次数 SUM(pv_cnt)
- `total_collect_cnt`: 按 user_id 汇总收藏次数 SUM(collect_cnt)
- `total_cart_cnt`: 按 user_id 汇总加购行为次数 SUM(cart_cnt)

---

### R0004 - 用户中心宽表最终装配

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_user_center_f` |
| 设计意图 | 以 tmp1（用户基础）为主表，LEFT JOIN tmp2（订单）/tmp3（行为）中间表，并通过 CTE 内联聚合优惠券/退款/购物车事实表，计算 RFM 评分、转化率、价值分层等衍生字段，产出最终宽表。 |
| 字段数 | 19 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| tmp1 | main |  |
| tmp2 | LEFT JOIN | tmp1.user_id = tmp2.user_id |
| tmp3 | LEFT JOIN | tmp1.user_id = tmp3.user_id |
| coupon_agg | LEFT JOIN | tmp1.user_id = coupon_agg.user_id |
| refund_agg | LEFT JOIN | tmp1.user_id = refund_agg.user_id |
| cart_agg | LEFT JOIN | tmp1.user_id = cart_agg.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| tmp2 (订单汇总) | 是 |  |
| tmp3 (行为汇总) | 是 |  |
| coupon_agg (CTE) | 是 |  |
| refund_agg (CTE) | 是 |  |
| cart_agg (CTE) | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 15 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `avg_order_amount`: 平均客单价：历史消费金额 / 历史订单数，分母为 0 或 NULL 时返回 NULL（NULLIF 防除零）
- `rfm_r_score`: R 值：计算最近下单距今天数 DATEDIFF(CURDATE(), last_order_time) 后，全量用户 NTILE(5) 窗口分组打分（天数越小分越高）。无订单用户 last_order_time 为 NULL，R 值记 NULL 或最低分
- `rfm_f_score`: F 值：基于历史订单数 total_order_cnt，全量用户 NTILE(5) 窗口分组打分（订单越多分越高）。无订单用户记最低分
- `rfm_m_score`: M 值：基于历史消费金额 total_pay_amount，全量用户 NTILE(5) 窗口分组打分（金额越高分越高）。无消费用户记最低分
- `rfm_segment`: 用户价值分层：组合 R/F/M 三分值，按规则划分高价值/中价值/低价值/流失四档
- ...(共 19 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0004 | dwb_user_center_tmp1 |
| R0002 | R0004 | dwb_user_center_tmp2 |
| R0003 | R0004 | dwb_user_center_tmp3 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002, R0003 |
| 2 | R0004 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dw_slusr_dwb_user_center_f |
| 调度周期 | 0 0 2 * * ? |
| 任务组 | dw_slusr_user_center |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
