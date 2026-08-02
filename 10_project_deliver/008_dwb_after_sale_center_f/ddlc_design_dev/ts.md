# ETL 技术规格(TS)

> 目标表: `slas.dwb_after_sale_center_f`(售后服务中心宽表) - 生成 2026-08-02T22:45:19

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slas.dwb_after_sale_center_f`(售后服务中心宽表) |
| **I 视图** | `slas.dwb_after_sale_center_i`(F表镜像) |
| **目标粒度** | 每行一个售后服务记录 |
| **写入策略** | 全量调度 |
| **分布键** | refund_id |
| **字段统计** | 业务 20 + 审计 4 = 总计 24 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | sdref.dwd_refund_f | 退款事实表 | drf |
| 2 | sdord.dwd_order_f | 订单明细事实表 | dof |
| 3 | dim.dim_user_f | 用户维度表 | duf |
| 4 | dim.dim_product_f | 商品维度表 | dpf |
| 5 | sdcs.dwd_service_ticket_f | 工单事实表 | dst |

---

## 2. 表模型设计

- **F表**: `dwb_after_sale_center_f`(存数据)
- **I视图**: `dwb_after_sale_center_i`(F表镜像, 对外查询)
- **分布键**: refund_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | slas.dwb_after_sale_center_f | 一行=一个售后服务记录 | 以退款事实表 dwd_refund_f 为主表，左关联订单、用户、商品、工单四表拼装售后中心宽表， 保持输出粒度=一个售后服务记录；对所有加工类字段做枚举值中文化与派生指标计算， 直取字段透传，审计字段按标准赋值，单条 INSERT 完成，无需物理中间表。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 4 |
| 粒度变化 | 无 (无粒度变化；需保证 JOIN 前 dof/dst 收敛至唯一粒度。) |
| 多步骤加工字段 | 5 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN 表数量 4（远低于阈值 12）；无粒度变化、无聚合后关联、无复杂关联链； 5 个加工字段均为简单枚举值中文化映射或单行算术派生（非"先聚合再关联"复杂逻辑）， 单条 INSERT 即可清晰表达全部加工，无需物理中间表，亦无需 CTE 拆分。

---

## 4. 规则详情

### R0001 - 售后服务中心宽表组装

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `slas.dwb_after_sale_center_f` |
| 设计意图 | 以退款事实表 dwd_refund_f 为主表，左关联订单、用户、商品、工单四表拼装售后中心宽表， 保持输出粒度=一个售后服务记录；对所有加工类字段做枚举值中文化与派生指标计算， 直取字段透传，审计字段按标准赋值，单条 INSERT 完成，无需物理中间表。 |
| 字段数 | 24 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| drf | main |  |
| dof | LEFT JOIN | drf.order_id = dof.order_id |
| duf | LEFT JOIN | drf.user_id = duf.user_id |
| dpf | LEFT JOIN | drf.product_id = dpf.product_id |
| dst | LEFT JOIN | drf.refund_id = dst.refund_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dof | 否 | JOIN 前对 dof 按 order_id 收敛至订单粒度：order_no 取唯一值、order_pay_amount 取订单实付金额单行（或订单级汇总），避免订单明细一对多导致退款记录 fan-out。 |
| duf | 是 |  |
| dpf | 是 |  |
| dst | 否 | JOIN 前对 dst 按 refund_id 收敛：若一个退款对应多张工单，取最新一条工单（或最新有效工单）的 ticket_id/ticket_status/handler_name，避免 fan-out。 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 15 |
| aggregate | 5 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `refund_type_name`: 退款类型中文化映射：将退款类型英文编码映射为中文名称—— ONLY_REFUND 映射为"仅退款"，RETURN_REFUND 映射为"退货退款"， EXCHANGE 映射为"换货"，其余取值映射为"其他"。
- `refund_status_name`: 退款状态中文化映射：将退款状态英文编码映射为中文名称—— APPLYING 映射为"申请中"，APPROVED 映射为"已同意"， SUCCESS 映射为"退款成功"，REJECTED 映射为"已拒绝"，其余取值映射为"其他"。
- `process_days`: 售后处理时长（天数）：以完成时间与申请时间的日期差为准； 若该退款尚未完成（完成时间为空），则以当前日期替代完成时间参与计算， 保证未完成单据也能体现已发生处理时长。
- `refund_rate`: 退款比例（百分比，保留两位小数）：退款金额除以订单实付金额再乘以100； 当订单实付金额为零或为空时，退款比例记为0，以规避除零异常。
- `ticket_status_name`: 工单状态中文化映射：将工单状态英文编码映射为中文名称—— PENDING 映射为"待处理"，PROCESSING 映射为"处理中"， RESOLVED 映射为"已解决"，CLOSED 映射为"已关闭"，其余取值映射为"其他"。
- ...(共 9 个加工字段)

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
| 调度任务 | dwb_after_sale_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | slas |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
