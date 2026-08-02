# ETL 技术规格(TS)

> 目标表: `slusr.dwb_user_profile_f`(用户画像宽表) - 生成 2026-08-02T23:05:46

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slusr.dwb_user_profile_f`(用户画像宽表) |
| **I 视图** | `slusr.dwb_user_profile_i`(F表镜像) |
| **目标粒度** | 每行一个用户画像记录 |
| **写入策略** | 全量调度 |
| **分布键** | user_id |
| **字段统计** | 业务 183 + 审计 4 = 总计 187 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | ods.ods_user_basic_f | 用户基础信息表 | oub |
| 2 | dim.dim_user_level_d | 用户等级维度表 | dul |
| 3 | dim.dim_region_d | 地区维度表 | drd |
| 4 | dim.dim_user_source_d | 用户来源维度表 | dus |

---

## 2. 表模型设计

- **F表**: `dwb_user_profile_f`(存数据)
- **I视图**: `dwb_user_profile_i`(F表镜像, 对外查询)
- **分布键**: user_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 4 |
| 粒度变化 | 无 (输入粒度=用户（ods_user_basic_f 一行一用户），输出粒度=用户，无聚合/无展开) |
| 多步骤加工字段 | 0 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: 仅 4 表关联（远低于 12 表阈值），无粒度变化，无聚合后关联，无复杂关联链； 所有数据加工字段均为单级行内转换，可在同一条 INSERT 内一次性完成。 无需建物理中间表，亦无需 CTE 收口。


---

## 4. 规则详情

### R0001 - 用户画像宽表全量装载

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_user_profile_f` |
| 设计意图 | 以 ods.ods_user_basic_f 为主表（一行=一个用户），LEFT JOIN 等级/地区/来源三张维度表 补齐画像属性，行内完成脱敏/翻译/日期拆解/VIP 判定等轻加工，全量覆盖目标宽表所有字段。 关联表数量少、无粒度变化、无聚合，单条 INSERT 即可，无需分段或建中间表。
 |
| 字段数 | 187 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| oub | main | ods.ods_user_basic_f 为主表 |
| dul | LEFT JOIN | oub.level_id = dul.level_id |
| drd | LEFT JOIN | oub.province_code = drd.region_code |
| dus | LEFT JOIN | oub.source_id = dus.source_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim.dim_user_level_d | 否 | 取当前有效等级行：限定 is_active=1 且 valid_from<=当前时间<valid_to（或取 update_time 最新的一行），保证每个 level_id 唯一 |
| dim.dim_region_d | 否 | 按地区层级收敛：限定 region_level 取省份层级（与 oub.province_code 对齐的层级），保证 region_code 唯一 |
| dim.dim_user_source_d | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 172 |
| aggregate | 11 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `user_phone_processed`: 手机号脱敏：保留前 3 位与后 4 位，中间用 **** 占位
- `gender_processed`: 性别代码翻译为中文：M 取男、F 取女，其余取未知
- `age_processed`: 由出生日期推算年龄：取当前日期的年份减去出生日期的年份
- `id_card_masked_processed`: 身份证号脱敏：保留前 6 位与后 4 位，中间用 ******** 占位
- `user_status_name_processed`: 用户状态代码翻译为中文：ACTIVE 取正常、INACTIVE 取未激活、BANNED 取封禁，其余取未知
- ...(共 15 个加工字段)

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
| 调度任务 | dwb_user_profile_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | dwb_user_profile |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
