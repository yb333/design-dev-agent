# ETL 技术规格(TS)

> 目标表: `slusr.dwb_user_center_f`(用户中心宽表) - 生成 2026-08-02T23:08:06

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
| **规则数** | 3 |

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
| R0001 | dwb_user_center_f_tmp1 | 一行=一个用户 | 将订单明细事实表聚合到用户粒度，产出历史订单统计指标，供 RFM 评分与最终宽表复用 |
| R0002 | dwb_user_center_f_tmp2 | 一行=一个用户 | 基于订单聚合指标用 NTILE(5) 窗口函数跨全量用户打分，产出 RFM 三维分数与价值分层 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 10 |
| 粒度变化 | 有 (5 张事实表（订单/行为/优惠券/退款/购物车）从明细粒度聚合到用户粒度；RFM 评分需跨全量用户 NTILE(5) 窗口排序) |
| 多步骤加工字段 | 11 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 命中多个分段阈值：多步骤加工字段≥5（RFM 三维评分+分层、转化率、退款率、客单价等 11 个）、有粒度变化（5 表聚合）、聚合后关联。订单聚合被 RFM 评分与最终装配复用→建物理中间表 tmp1；RFM 窗口评分独立加工且为关键属性→建物理中间表 tmp2；行为/优惠/退款/购物车聚合仅用一次→CTE 内联

---

## 4. 规则详情

### R0001 - 订单聚合中间表

| 项目 | 内容 |
|------|------|
| 场景 | 订单统计 |
| 执行序 | 1 |
| 产出表 | `dwb_user_center_f_tmp1` |
| 设计意图 | 将订单明细事实表聚合到用户粒度，产出历史订单统计指标，供 RFM 评分与最终宽表复用 |
| 字段数 | 5 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | FROM dwd_order_f dof |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f | 否 | GROUP BY user_id 收敛聚合（一个用户多条订单→一行统计） |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 5 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `total_order_cnt`: 从 dwd_order_f 按 user_id 分组，COUNT(*) 统计历史有效订单数（过滤 order_status NOT IN ('CANCELLED','DELETED')）
- `total_pay_amount`: 从 dwd_order_f 按 user_id 分组，SUM(pay_amount) 统计历史有效订单消费金额（过滤 order_status NOT IN ('CANCELLED','DELETED')）
- `avg_order_amount`: 平均客单价 = 总消费金额 / 历史订单数，分母为 0 时返回 NULL（NULLIF 防除零）
- `last_order_time`: 从 dwd_order_f 按 user_id 分组，MAX(create_time) 取最近一次下单时间
- `first_order_time`: 从 dwd_order_f 按 user_id 分组，MIN(create_time) 取首次下单时间

---

### R0002 - RFM 评分中间表

| 项目 | 内容 |
|------|------|
| 场景 | 用户价值分层 |
| 执行序 | 2 |
| 产出表 | `dwb_user_center_f_tmp2` |
| 设计意图 | 基于订单聚合指标用 NTILE(5) 窗口函数跨全量用户打分，产出 RFM 三维分数与价值分层 |
| 字段数 | 4 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| tmp1 | main | FROM dwb_user_center_f_tmp1 tmp1 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwb_user_center_f_tmp1 | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `rfm_r_score`: 第一步：DATEDIFF(CURDATE(), last_order_time) 计算最近下单距今天数（R 值，越小越优）；第二步：NTILE(5) 窗口函数按 R 值升序分 5 组，天数越小分数越高（5→1）
- `rfm_f_score`: 第一步：取 total_order_cnt 作为消费频次（F 值）；第二步：NTILE(5) 窗口函数按 F 值降序分 5 组，订单越多分数越高
- `rfm_m_score`: 第一步：取 total_pay_amount 作为消费金额（M 值）；第二步：NTILE(5) 窗口函数按 M 值降序分 5 组，金额越高分数越高
- `rfm_segment`: 组合 RFM 三维分数划分价值分层：高价值（R/F/M 均≥4）、中价值（任两维≥4）、低价值（任一维≥3）、流失（R≤2 且 F≤2）

---

### R0003 - 用户中心宽表装配

| 项目 | 内容 |
|------|------|
| 场景 | 用户基础属性 |
| 执行序 | 3 |
| 产出表 | `dwb_user_center_f` |
| 设计意图 | 以 dim_user_f 为主表左联维度表与中间表，CTE 聚合行为/优惠/退款/购物车事实，计算派生转化率与标签，产出最终宽表 |
| 字段数 | 37 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| duf | main | FROM dim_user_f duf |
| dul | LEFT JOIN | duf.level_id = dul.level_id |
| drf | LEFT JOIN | duf.province_code = drf.region_code |
| drf_city | LEFT JOIN | duf.city_code = drf_city.region_code |
| dus | LEFT JOIN | duf.source_id = dus.source_id |
| tmp1 | LEFT JOIN | duf.user_id = tmp1.user_id |
| tmp2 | LEFT JOIN | duf.user_id = tmp2.user_id |
| behavior_agg | LEFT JOIN | duf.user_id = behavior_agg.user_id |
| coupon_agg | LEFT JOIN | duf.user_id = coupon_agg.user_id |
| refund_agg | LEFT JOIN | duf.user_id = refund_agg.user_id |
| cart_agg | LEFT JOIN | duf.user_id = cart_agg.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_user_level_f | 是 |  |
| dim_region_f | 是 |  |
| dim_user_source_f | 是 |  |
| dwb_user_center_f_tmp1 | 是 |  |
| dwb_user_center_f_tmp2 | 是 |  |
| CTE 聚合(behavior/coupon/refund/cart) | 是 | GROUP BY user_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 19 |
| direct | 14 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `user_phone_masked`: 手机号脱敏：CONCAT(LEFT(user_phone,3),'****',RIGHT(user_phone,4))，保留前 3 位与后 4 位
- `gender_name`: 性别代码转中文：M→男，F→女，其他→未知
- `age`: 年龄 = YEAR(CURDATE()) - YEAR(birthday)
- `register_days`: 注册天数 = DATEDIFF(CURDATE(), register_time)
- `city_name`: 通过 city_code 二次关联 dim_region_f 获取城市名称（dim_region_f 关联两次：一次取省份 province_code，一次取城市 city_code）
- ...(共 23 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0002 | dwb_user_center_f_tmp1 |
| R0001 | R0003 | dwb_user_center_f_tmp1 |
| R0002 | R0003 | dwb_user_center_f_tmp2 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001 |
| 2 | R0002 |
| 3 | R0003 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_user_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | slusr |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
