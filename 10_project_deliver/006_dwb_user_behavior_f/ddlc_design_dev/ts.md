# ETL 技术规格(TS)

> 目标表: `slord.dwb_user_behavior_f`(用户行为宽表) - 生成 2026-08-02T23:31:26

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slord.dwb_user_behavior_f`(用户行为宽表) |
| **I 视图** | `slord.dwb_user_behavior_i`(F表镜像) |
| **目标粒度** | 每行一个用户行为记录 |
| **写入策略** | 全量调度 |
| **分布键** | behavior_id |
| **字段统计** | 业务 260 + 审计 4 = 总计 264 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | ods.ods_order_main_f | 订单主表 | oom |
| 2 | dim.dim_product_d | 商品维度表 | dpd |
| 3 | dim.dim_user_base_d | 用户基础维度表 | dub |
| 4 | ods.ods_content_interaction_f | 内容互动表 | oci |
| 5 | dim.dim_content_d | 内容维度表 | dcd |
| 6 | dim.dim_user_base_d | 用户基础维度表 | dub7 |
| 7 | ods.ods_social_relation_f | 社交关系表 | osr |
| 8 | dim.dim_user_profile_d | 用户画像维度表 | dup |
| 9 | dim.dim_user_base_d | 用户基础维度表 | dub10 |

---

## 2. 表模型设计

- **F表**: `dwb_user_behavior_f`(存数据)
- **I视图**: `dwb_user_behavior_i`(F表镜像, 对外查询)
- **分布键**: behavior_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 9 |
| 粒度变化 | 无 (三场景输入/输出均为'每行=一个用户行为记录'，UNION ALL 行级追加，无聚合无展开) |
| 多步骤加工字段 | 0 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: 三场景分支结构清晰、无聚合无粒度变化、JOIN 数 9 < 阈值 12，单条 UNION ALL INSERT 即可完成，无需中间表

---

## 4. 规则详情

### R0001 - 用户行为宽表三场景 UNION ALL 加工

| 项目 | 内容 |
|------|------|
| 场景 | 电商交易/内容互动/社交关系 |
| 执行序 | 1 |
| 产出表 | `dwb_user_behavior_f` |
| 设计意图 | 将三类互斥的用户行为事件流（电商交易、内容互动、社交关系）按统一的 用户+行为+领域扩展 字段模型 UNION ALL 合并到一张行为宽表。 因 user_* 与通用行为字段在三场景物理上同属每一行，无法分配到多条场景规则， 故用单条 INSERT 承载全部 184 个目标字段，三场景作为并联 JOIN 子图 在同一规则的 SQL 内并行产出，最终 UNION ALL。
 |
| 字段数 | 184 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| oom | main | 场景1 主表 ods_order_main_f |
| dpd | LEFT JOIN | oom.product_id = dpd.product_id |
| dub | LEFT JOIN | oom.user_id = dub.user_id |
| oci | main | 场景2 主表 ods_content_interaction_f |
| dcd | LEFT JOIN | oci.content_id = dcd.content_id |
| dub7 | LEFT JOIN | oci.user_id = dub7.user_id |
| osr | main | 场景3 主表 ods_social_relation_f |
| dup | LEFT JOIN | osr.user_id = dup.user_id |
| dub10 | LEFT JOIN | osr.user_id = dub10.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_user_base_d (dub / dub7 / dub10) | 是 | 维度表按 user_id 主键关联，默认唯一 |
| dim_product_d (dpd) | 是 | 维度表按 product_id 主键关联，默认唯一 |
| dim_content_d (dcd) | 是 | 维度表按 content_id 主键关联，默认唯一 |
| dim_user_profile_d (dup) | 是 | 维度表按 user_id 主键关联，默认唯一 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 160 |
| aggregate | 20 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `user_user_phone`: 手机号脱敏：保留前 3 位和后 4 位，中间用 **** 替换
- `user_gender`: 性别映射：M→男，F→女，其他→未知
- `user_age`: 年龄 = 当前日期的年份减去出生日期的年份
- `user_register_date`: 注册日期 = 取注册时间的日期部分
- `user_user_status_name`: 用户状态映射：ACTIVE→正常，INACTIVE→未激活，BANNED→封禁，其他→未知
- ...(共 24 个加工字段)

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
| 调度任务 | slord_dwb_user_behavior_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | - |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
