# ETL 技术规格(TS)

> 目标表: `slord.dwb_user_behavior_f`(用户行为宽表) - 生成 2026-08-03T23:27:00

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
| **规则数** | 4 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | ods.ods_order_main_f | 订单主表 | oom |
| 2 | dim.dim_product_d | 商品维度表 | dpd |
| 3 | dim.dim_user_base_d | 用户基础维度表 | dub |
| 4 | ods.ods_content_interaction_f | 内容互动表 | oci |
| 5 | dim.dim_content_d | 内容维度表 | dcd |
| 6 | dim.dim_user_base_d | 用户基础维度表 | dub5 |
| 7 | ods.ods_social_relation_f | 社交关系表 | osr |
| 8 | dim.dim_user_profile_d | 用户画像维度表 | dup |
| 9 | dim.dim_user_base_d | 用户基础维度表 | dub8 |

---

## 2. 表模型设计

- **F表**: `dwb_user_behavior_f`(存数据)
- **I视图**: `dwb_user_behavior_i`(F表镜像, 对外查询)
- **分布键**: behavior_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | dwb_user_behavior_tmp1 | 一行=一个电商交易行为(含订单+商品维度) | 从订单主表 ods_order_main_f 出发, LEFT JOIN 商品维度 dim_product_d 取商品属性, 加工电商交易场景的行为明细(订单+商品共50字段), 产出到场景中间表 tmp1 供 F 表 UNION 合并 |
| R0002 | dwb_user_behavior_tmp2 | 一行=一个内容互动行为(含互动+内容维度) | 从内容互动表 ods_content_interaction_f 出发, LEFT JOIN 内容维度 dim_content_d 取内容属性, 加工内容互动场景的行为明细(互动+内容共50字段), 产出到场景中间表 tmp2 供 F 表 UNION 合并 |
| R0003 | dwb_user_behavior_tmp3 | 一行=一个社交关系行为(含关系+用户画像维度) | 从社交关系表 ods_social_relation_f 出发, LEFT JOIN 用户画像维度 dim_user_profile_d 取画像属性, 加工社交关系场景的行为明细(关系+画像共40字段), 产出到场景中间表 tmp3 供 F 表 UNION 合并 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 3 |
| 粒度变化 | 无 (输入输出粒度一致, 每行=一个用户行为记录; 3 场景各自独立加工保持粒度, UNION ALL 仅纵向合并不改变粒度) |
| 多步骤加工字段 | 13 |
| 聚合后关联 | 否 |

**分段结论**: 分段
**理由**: 3 个业务场景(电商交易/内容互动/社交关系)来自不同 ods 主表, 关联不同维度表, 业务实质不同, 天然需要分场景加工; 每场景独立产出中间表后 UNION ALL 合并到 F 表, 既保持各场景加工逻辑独立可校验, 又能在 schedule 上并行执行缩短 SLA. 不分段无法表达多场景并行的执行语义.

---

## 4. 规则详情

### R0001 - 电商交易场景加工

| 项目 | 内容 |
|------|------|
| 场景 | 电商交易 |
| 执行序 | 1 |
| 产出表 | `dwb_user_behavior_tmp1` |
| 设计意图 | 从订单主表 ods_order_main_f 出发, LEFT JOIN 商品维度 dim_product_d 取商品属性, 加工电商交易场景的行为明细(订单+商品共50字段), 产出到场景中间表 tmp1 供 F 表 UNION 合并 |
| 字段数 | 50 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| oom | main | 主表, ods_order_main_f 全量扫描 |
| dpd | LEFT JOIN | oom.product_id = dpd.product_id |
| dub | LEFT JOIN | oom.user_id = dub.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_product_d | 是 |  |
| dim_user_base_d | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 48 |
| aggregate | 2 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `order_order_status_name`: 订单状态码翻译为中文: PENDING→待支付, PAID→已支付, SHIPPED→已发货, COMPLETED→已完成, CANCELLED→已取消, 其他码→未知
- `prod_profit_rate`: 商品利润率(%)=(商品价格-成本价)/商品价格×100; 价格≤0 时取 0 防止除零

---

### R0002 - 内容互动场景加工

| 项目 | 内容 |
|------|------|
| 场景 | 内容互动 |
| 执行序 | 1 |
| 产出表 | `dwb_user_behavior_tmp2` |
| 设计意图 | 从内容互动表 ods_content_interaction_f 出发, LEFT JOIN 内容维度 dim_content_d 取内容属性, 加工内容互动场景的行为明细(互动+内容共50字段), 产出到场景中间表 tmp2 供 F 表 UNION 合并 |
| 字段数 | 50 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| oci | main | 主表, ods_content_interaction_f 全量扫描 |
| dcd | LEFT JOIN | oci.content_id = dcd.content_id |
| dub5 | LEFT JOIN | oci.user_id = dub5.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_content_d | 是 |  |
| dim_user_base_d | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 46 |
| aggregate | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `content_interaction_type_name`: 互动类型码翻译为中文: VIEW→浏览, LIKE→点赞, COMMENT→评论, SHARE→分享, COLLECT→收藏, 其他码→其他
- `content_duration_minutes`: 浏览时长(分钟)=浏览时长秒数/60
- `content_comment_word_count`: 评论字数=评论内容字符串长度(字符数)
- `content_publish_date`: 内容发布日期=发布时间的日期部分

---

### R0003 - 社交关系场景加工

| 项目 | 内容 |
|------|------|
| 场景 | 社交关系 |
| 执行序 | 1 |
| 产出表 | `dwb_user_behavior_tmp3` |
| 设计意图 | 从社交关系表 ods_social_relation_f 出发, LEFT JOIN 用户画像维度 dim_user_profile_d 取画像属性, 加工社交关系场景的行为明细(关系+画像共40字段), 产出到场景中间表 tmp3 供 F 表 UNION 合并 |
| 字段数 | 40 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| osr | main | 主表, ods_social_relation_f 全量扫描 |
| dup | LEFT JOIN | osr.user_id = dup.user_id |
| dub8 | LEFT JOIN | osr.user_id = dub8.user_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dim_user_profile_d | 是 |  |
| dim_user_base_d | 是 |  |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 39 |
| aggregate | 1 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `social_relation_type_name`: 关系类型码翻译为中文: FOLLOW→关注, FRIEND→好友, BLOCK→屏蔽, BLACKLIST→黑名单, 其他码→其他

---

### R0004 - F表多场景合并

| 项目 | 内容 |
|------|------|
| 场景 | 多场景合并 |
| 执行序 | 2 |
| 产出表 | `dwb_user_behavior_f` |
| 设计意图 | 将 3 个场景中间表(tmp1/tmp2/tmp3)UNION ALL 合并写入 F 表 dwb_user_behavior_f; 同时承载 3 场景共用字段(behavior_* 时间派生/is_weekend/time_period/user_* 用户维度/4 审计字段); 时间派生和用户脱敏的 design_logic 在此登记一次, coder 阶段在 3 个场景 SQL 里复用; 配套由 coder 生成 I 视图 dwb_user_behavior_i (SELECT * FROM F 表) |
| 字段数 | 44 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 27 |
| aggregate | 13 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `behavior_date`: 行为日期=行为时间的日期部分(电商用 create_time, 内容用 interaction_time, 社交用 create_time)
- `behavior_hour`: 行为小时=行为时间的小时部分(0-23)
- `behavior_weekday`: 行为星期=行为时间是周几(DAYOFWEEK, 1-7)
- `behavior_month`: 行为月份=行为时间的月份部分(1-12)
- `behavior_quarter`: 行为季度=行为时间的季度部分(1-4)
- ...(共 17 个加工字段)

---

## 5. 数据流向

**血缘关系**:

| from | to | 中间表 |
|------|-----|--------|
| R0001 | R0004 | dwb_user_behavior_tmp1 |
| R0002 | R0004 | dwb_user_behavior_tmp2 |
| R0003 | R0004 | dwb_user_behavior_tmp3 |

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001, R0002, R0003 |
| 2 | R0004 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_user_behavior_f_load |
| 调度周期 | 0 0 3 * * ? |
| 任务组 | dwb_user_behavior |

---

## 7. 数据质量检查(DQ)

| 规则ID | 名称 | 类型 | 对象 |
|--------|------|------|------|
| DQ_001 | behavior_id 全局唯一性检查 | uniqueness | behavior_id |
| DQ_002 | 场景来源完整性检查 | completeness | behavior_id |
