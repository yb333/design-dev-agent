# ETL 技术规格(TS)

> 目标表: `slmar.dwb_marketing_center_f`(营销中心宽表) - 生成 2026-08-02T22:48:45

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
| **规则数** | 2 |

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
| R0001 | dwb_marketing_order_tmp | 一行=一个活动 | 将订单明细事实表按活动ID聚合收口到活动粒度，产出订单域核心指标（订单数/GMV/参与人数/优惠金额/新客占比），为最终宽表提供订单指标输入 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 4 |
| 粒度变化 | 有 (订单明细（同一活动多笔订单）与优惠券使用（同一活动多笔使用）均为明细粒度，需先按 activity_id 聚合收口到活动粒度后再关联到活动主表（聚合后关联）) |
| 多步骤加工字段 | 6 |
| 聚合后关联 | 是 |

**分段结论**: 分段
**理由**: 多项复杂度指标触发分段：(1) 多步骤加工字段 6 个（达到阈值 5）：含 5 订单聚合指标（order_cnt/gmv_amount/participant_cnt/total_discount_amount/new_user_rate）+ 1 ROI 跨源派生；(2) 存在粒度变化：订单明细（多行/活动）需聚合收口到活动粒度；(3) 存在聚合后关联：订单与优惠券使用均需先 GROUP BY activity_id 再 JOIN 到活动主表。采用分段策略：将 5 个订单域聚合指标收口为物理中间表 dwb_marketing_order_tmp（5 字段内聚且可独立校验，被宽表人均消费/ROI 复用）；优惠券使用成本仅用于 ROI 单点计算（用一次），用 CTE coupon_cost_agg 内联即可，无需建物理表。JOIN 表数 4 张（dat/dcf/dcu-CTE/dof→tmp1）虽未超阈值，但多步骤字段与粒度变化已充分支持分段决策。

---

## 4. 规则详情

### R0001 - 活动订单指标中间表

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_marketing_order_tmp` |
| 设计意图 | 将订单明细事实表按活动ID聚合收口到活动粒度，产出订单域核心指标（订单数/GMV/参与人数/优惠金额/新客占比），为最终宽表提供订单指标输入 |
| 字段数 | 5 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dof | main | 单源表聚合，无关联 |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_order_f (dof) | 是 | GROUP BY activity_id 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| aggregate | 5 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `order_cnt`: 按 activity_id 分组统计关联订单数 COUNT(*)，仅计入未取消的有效订单
- `gmv_amount`: 按 activity_id 分组对订单支付金额求和 SUM(pay_amount)，得到活动 GMV
- `participant_cnt`: 按 activity_id 分组统计去重参与用户数 COUNT(DISTINCT user_id)
- `total_discount_amount`: 按 activity_id 分组对订单优惠金额求和 SUM(discount_amount)
- `new_user_rate`: 活动期间新用户订单数除以总订单数乘以100得到新客占比百分比。⚠️新用户识别需定义：假设以用户首次下单时间落在活动期间判定为新客，需在订单明细上按用户取首单日期比对活动起止时间（语义待人工确认）

---

### R0002 - 营销中心宽表组装

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 2 |
| 产出表 | `dwb_marketing_center_f` |
| 设计意图 | 以活动事实表为主表，LEFT JOIN 活动类型维、优惠券维、优惠券使用成本CTE、订单指标中间表，装配全部宽表字段（活动直取+字典翻译+日期差+优惠券直取与派生+订单派生指标+ROI+审计） |
| 字段数 | 24 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| daf | main | 活动事实表主表 |
| dat | LEFT JOIN | daf.activity_type = dat.type_code |
| dcf | LEFT JOIN | daf.activity_id = dcf.activity_id |
| coupon_cost_agg | LEFT JOIN | daf.activity_id = coupon_cost_agg.activity_id |
| dwb_marketing_order_tmp | LEFT JOIN | daf.activity_id = dwb_marketing_order_tmp.activity_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwd_activity_f (daf) | 是 | 无需对齐 |
| dim_activity_type_f (dat) | 是 | 无需对齐 |
| dim_coupon_f (dcf) | 否 | 假设一活动一主券或取首条/需人工确认 |
| coupon_cost_agg (CTE) | 是 | 已 GROUP BY 收敛 |
| dwb_marketing_order_tmp | 是 | 已 GROUP BY 收敛 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 13 |
| aggregate | 7 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `activity_type_name`: 活动类型编码字典翻译：SECKILL转秒杀、GROUPBUY转团购、PRESALE转预售、FULL_REDUCE转满减、FULL_GIFT转满赠，其余为其他
- `activity_status_name`: 活动状态编码字典翻译：DRAFT转草稿、PENDING转待开始、RUNNING转进行中、ENDED转已结束，其余为其他
- `activity_days`: 结束时间减开始时间的天数差
- `coupon_type_name`: 优惠券类型编码字典翻译：FULL_REDUCE转满减券、DISCOUNT转折扣券、CASH转现金券，其余为其他
- `coupon_use_rate`: 优惠券已使用量除以发放总量乘以100得到使用率百分比（发放总量为0时返回空值避免除零）
- ...(共 11 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0002 | dwb_marketing_order_tmp |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001 |
| 2 | R0002 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_marketing_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | dwb_marketing_center |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
