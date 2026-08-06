# 设计指南

> designer agent 做设计判断时的参考规范。
> 只含 designer 用得上的：命名规范、物理设计决策（分布键/分区）、字段分组原则。
> DDL 模板、编码规范归 coding skill（dws-coding-standards.md）。

---

## 一、命名规范

### 1.1 分层前缀

| 前缀 | 层级 | 用途 |
|------|------|------|
| `DWD` | 接入层 | 贴源数据接入 |
| `DWB` | 明细层 | 明细数据加工 |
| `DWL` | 连接层 | 关联、宽表等连接加工 |

### 1.2 表命名格式

```
{前缀}_{业务对象/领域}_{数据实质简称}{后缀}
```

| 后缀 | 含义 |
|------|------|
| `F` | 物理表（存数据） |
| `I` | 视图（F 表镜像，对外消费接口） |
| `tmp{n}` | 临时表（ETL 加工中间表，n 从 1 开始） |

> **F+I 成对**：I 是 F 的稳定消费接口（`SELECT * FROM ..._f`），字段不变则 F 逻辑变化不影响 I。

示例：`DWB_contract_center_F`（合同中心明细物理表）、`DWL_order_product_F`（订单商品连接物理表）

### 1.3 字段命名后缀

| 后缀 | 类型 | 示例 |
|------|------|------|
| `_id` | BIGINT | `user_id`, `order_id` |
| `_code` | VARCHAR | `product_code`, `dept_code` |
| `_name` | VARCHAR | `product_name` |
| `_amt` | DECIMAL | `order_amt`, `pay_amt` |
| `_rate` | DECIMAL | `tax_rate`, `discount_rate` |
| `_qty` | DECIMAL | `order_qty`, `ship_qty` |
| `_num` | BIGINT | `order_num`, `item_num` |
| `_dt` | DATE | `order_dt` |
| `_time` | TIMESTAMP | `create_time` |
| `_flag` | NVARCHAR(1) | `del_flag` |
| `_type` | VARCHAR | `order_type` |
| `_desc` | VARCHAR | `product_desc` |

布尔字段用 `is_` 前缀或 `_flag` 后缀（`is_valid` / `del_flag`）。

---

## 二、物理设计决策

> **DWS 物理设计标准（统一）**：列存（ORIENTATION=COLUMN）+ 哈希分布（DISTRIBUTE BY HASH）+ LOW 压缩。
> 这些是 coder 建表时套用的固定标准，designer 不需要管具体语法。
> designer 要判断的是：**分布键选哪个、要不要分区**。

### 2.1 分布键选择

**选择优先级**：

```
1. 经常 JOIN 的字段（多表 JOIN 时各表分布键必须一致 → 本地关联）
2. 高基数字段（避免数据倾斜，如 order_id 而非 status）
3. WHERE 高频过滤字段
```

| 表类型 | 推荐分布键 |
|--------|------------|
| 事实表 | 业务主键（如 `order_id`、`contract_id`） |
| 维度表 | 通常用 REPLICATION（小表广播） |
| 中间表 | 与下游 JOIN 字段一致 |

**designer 判断要点**：
- 多表 JOIN 时，分布键必须一致，否则关联时数据重分布
- 低基数字段（如 status、gender）会导致数据倾斜，不能用
- 分布键选错 → 运行时倾斜，但这是 coder 执行时才能检测（`table_skewness`）

### 2.2 分区策略

| 场景 | 分区策略 |
|------|----------|
| **默认** | **不分区** |
| 有会计期需求 | 按 `account_period` 分区（LIST 或 RANGE） |

**designer 判断要点**：
- 绝大多数表不分区
- 只有明确的会计期/按时间切片查询需求时才分区
- 分区决策写在 `meta.schedule` 或复杂度分析里（如果是分段考虑）

---

## 三、字段分组原则（避免重复归类）

designer 做规则拆分时，每个字段必须**只归属一个规则**。判断字段归哪个规则的原则：

```
字段归哪个规则，取决于它的产出逻辑（design_logic）来自哪：
- 字段值直接从某源表取（direct）       → 归该源表所在的规则
- 字段值由多字段加工算出（aggregate）  → 归执行该加工的规则
- 字段值是固定赋值（assign）           → 归目标表对应的规则
- 字段来自中间表                       → 归产出该中间表的规则
```

**常见错误**（以电商为例）：
- `fav_pay_method`（来自用户画像中间表）误归"支付信息"→ 应归"用户维度"规则，因为它从用户画像产出
- `product_sales_cnt`（来自商品画像中间表）误归"订单信息"→ 应归"商品维度"规则

**designer 判断依据**：看 design_logic 里"数据从哪来、怎么算"，而不是看字段名像什么业务领域。

---

## 四、步骤拆分与中间表决策

designer 评估复杂度后决定**是否拆分步骤、是否建物理中间表**。
这决定每个规则的 step_type（详见 §6）。

### 4.1 复杂度评估指标

| 指标 | 阈值 | 说明 |
|------|------|------|
| JOIN 表数量 | > 12 | 关联表过多，单条 INSERT 难以一次写对 |
| 多步骤加工字段数 | ≥ 5 | 多个字段需要先聚合再关联、先拆再拼 |
| 粒度变化 | 有即声明 | 输入输出粒度不一致（聚合/展开） |
| 聚合后关联 | 有 | 先 GROUP BY 再 JOIN，逻辑复杂 |
| 复杂关联链 | ≥ 3 层 | A→B→C 串联依赖 |

命中任一阈值 → 考虑拆成多步骤（物理中间表收口）。

### 4.2 中间表 vs CTE 决策（业界标准）

**默认策略：从 CTE 开始，必要时物化成物理中间表。**
（业界共识，Brent Ozar + Microsoft Azure SQL 官方推荐）

拆物理中间表 vs 用 CTE 内联，**不是风格偏好，是有工程标准的决策**。
满足以下任一条件，就该物化成物理中间表（step_type=aggregate）：

| 判断维度 | CTE 够用 | 必须物化物理中间表 |
|---------|---------|-------------------|
| 中间结果引用次数 | 只用一次 | **多次引用**（重算浪费）|
| 行估算准确性 | 优化器估算准 | **估算偏差 >10x**（误差放大致性能崩）|
| 数据量 | 小 | **大**（需索引加速 JOIN）|
| 可调试性 | 不需检查中间数据 | **需要检查点**（排查问题）|
| 跨步骤传递 | 单条 SQL 内 | **跨步骤**（多 rule 数据流）|

> 真实案例：CTE 重的过程 90 分钟 → 改成索引临时表后 15 秒（差 360 倍）。
> 多步骤 ETL 天然适合物理中间表——每步产出可检查、可复用、可索引。

**反过来**：简单场景（JOIN 少、中间结果只用一次、数据量小）用 CTE 够，不必拆物理表（step_type=full，CTE 内联即可）。

### 4.3 螺旋式中间表设计

中间表设计是螺旋的——先骨架后回填：
1. **先骨架**：复杂度评估后决定建几个中间表，定表名/粒度/用途
2. **字段逻辑**：确定每个字段加工逻辑时，识别哪些字段落在中间表
3. **回填字段**：从字段分配回填出每个中间表的完整字段清单

> 中间表的字段绝大多数与目标表字段同名同类型（透传/聚合），极少量 designer 自建字段（辅助计算中间产物）。中间表统一加审计字段。

### 4.4 step_type 决策树

按以下顺序判断每个规则的 step_type：

```
该规则是否处理增量数据？
├─ 否（全量）
│   ├─ 命中复杂度阈值（§4.1）且满足物化条件（§4.2）？
│   │   ├─ 是 → step_type=aggregate（聚合中间表，target_role=intermediate）
│   │   └─ 否 → step_type=full（单规则直灌目标，CTE 内联，target_role=target）
│   └─ 该规则是否读中间表装配目标？
│       └─ 是 → step_type=full（装配步骤，target_role=target，reads=[中间表]）
└─ 是（增量，详见 §5.2）
    ├─ 该规则是从源表取增量到临时表？
    │   └→ step_type=incremental_extract（target_role=intermediate，produces_for=[merge步骤]）
    └─ 该规则是合并临时表到目标？
        └→ step_type=merge（target_role=target，reads=[临时表]，load_mode=merge_into/分区删插）
```

## 五、调度设计

### 5.1 调度类型

从 RS L07 的调度频率推导 `schedule_type`：

| RS L07 调度频率 | schedule_type | 说明 |
|----------------|---------------|------|
| T+1、一天一调、日调度 | `daily` | 最常见 |
| 一天多调、小时级 | `hourly` | 高频周期 |
| 分钟级、准实时 | `realtime` | 高频周期（俗称实时） |

### 5.2 多源增量设计

当 RS L07 的"增量识别方式"不是"不涉及"时，该资产为增量场景。增量是规则级的——同一资产里有的规则全量、有的增量。

> **业界共识（Skyvia / Databricks / Microsoft Fabric）**：增量加载的标准模式是
> "源表取增量 → 临时表（staging）中转 → MERGE 合并到目标表"。临时表中转的原因：
> 可验证可回滚、幂等（重跑不重复）、性能（MERGE 在临时表和目标表间做比边查边写快）。

#### 增量识别（从 RS 增量表读）

RS L07 的"增量表及增量字段"段给出**驱动表 + 增量字段**：

| 来源表 | 增量字段 |
|--------|---------|
| ods.ods_order_f | update_time |
| ods.ods_payment_f | dt |

**多驱动表**：每张驱动表各自有增量范围（一张按 update_time 水位线、一张按 dt 分区）。
这不是"一个主表驱动全部"，而是**各自独立取增量**（业界叫 modular pipelines）。

| 识别方式 | 说明 | 示例 |
|---------|------|------|
| **水位线（时间戳）** | 源表有 update_time，按时间范围过滤 | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| **分区字段** | 源表有日期分区，按分区读取 | `dt >= '${BIZ_DATE_START}' AND dt < '${BIZ_DATE_END}'` |

#### 多驱动表数据流（标准模式）

```
驱动表A（按 update_time 取增量）→ 临时表 tmp_a  [step_type=incremental_extract]
驱动表B（按 dt 取增量）         → 临时表 tmp_b  [step_type=incremental_extract]
tmp_a + tmp_b → MERGE 合并      → 目标表        [step_type=merge]
```

- 每个驱动表一个 `incremental_extract` 规则，产出各自的物理临时表（target_role=intermediate）
- 临时表**每次重建**（先 truncate 再灌，用完即丢——业界 staging 模式）
- 最终一个 `merge` 规则读临时表 + 必要维表，合并到目标表

#### 合并方式（看表类型选 load_mode）

| load_mode | 说明 | 典型场景 |
|-----------|------|---------|
| `merge_into` | Upsert（有则更新、无则插入）| 一般增量，MERGE key = business_key |
| `truncate_partition` | 按分区清空再插 | 会计期/分区日增量（清当期/当天分区再灌） |
| `delete` | 按条件删后插 | 可能有数据修正的表（删当期再插） |
| `no_delete` | 直接追加 | 事件流水（只加不改） |

**MERGE key**：复用目标表的 `business_key`（业务主键）。

#### 增量参数

增量过滤用**起止双参数**：
- `BIZ_DATE_START`：增量起始日期
- `BIZ_DATE_END`：增量结束日期

在 `params` 段声明，在 `lts_params` 段配置 LTS 侧变量赋值（如 `V_BIZ_DATE_START → BIZ_DATE_START`）。

#### 初始化设计

初始化和增量是**同一套数据流、WHERE 不同**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `incremental.filter` | 增量 WHERE | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| `incremental.init_filter` | 初始化 WHERE | `1=1`（全量）或 `dt >= '2024-01-01'`（限定范围） |
| `incremental.init_time_range` | 初始化时间范围（RS L07） | ALL / 2024-01-01 |
| `incremental.init_strategy` | 初始化策略描述 | 首次全量加载，后续增量 |

初始化时，extract 步骤的 WHERE 换成 init_filter（全量或初始范围），merge 步骤的 load_mode 从 merge_into 换成 truncate_table（初始化是全量覆盖）。

#### 初始化实现方式（init_mode）—— designer 必须决策

初始化在术加平台怎么落地，**是设计决策，不是部署细节**。

**核心判断标准：初始化和增量的差异是不是只在 WHERE？**

- **只在 WHERE 不同** → 参数控制（同一套规则组，WHERE 用条件分支）
- **差异超出 WHERE**（FROM/JOIN/字段处理不同）→ 独立规则组（两套规则各自简洁）

| init_mode | 怎么做 | 什么时候选 |
|-----------|--------|-----------|
| **参数控制** | 同一规则组，传 ALL 或日期参数。SQL 里 WHERE 用条件分支 | 初始化和增量的差异只在 WHERE（如增量 `WHERE dt=今天`，初始化 `WHERE 1=1`） |
| **独立规则组** | 另建一个规则组，专门跑初始化 | 初始化的加工逻辑跟增量有本质差异（FROM 读不同范围、JOIN 取历史维表版本、字段处理不同） |

#### 增量场景矩阵

| 场景 | 驱动表 | extract step_type | merge load_mode | init_filter |
|------|--------|------------------|----------------|-------------|
| 分区日增量 | 分区表 | incremental_extract | truncate_partition | `1=1` |
| 时间戳追加 | 时间戳表 | incremental_extract | no_delete | `1=1` |
| 时间戳重刷 | 时间戳表 | incremental_extract | delete | `1=1` |
| Upsert增量 | 时间戳表 | incremental_extract | merge_into | `1=1` |
| 多源增量 | 多驱动表 | 多个 incremental_extract | merge_into | `1=1` |

### 5.3 依赖类型

LTS 调度平台的跨任务依赖（弱依赖），每个上游依赖选 dep_type：

| 类型 | 含义 | 典型场景 |
|------|------|---------|
| **宽依赖**（默认） | 当天任意时间或计划时间前后 N 小时内完成过就行 | 大部分场景 |
| **同周期依赖** | 依赖和被依赖的调度频率时间点完全相同，跑完才轮到我 | 同频任务间依赖 |
| **时间点依赖** | 等到依赖任务在指定时间点执行完成后再跑 | 精确控制执行顺序 |
| **上周期依赖** | 当前任务的计划时间匹配被依赖任务的上一个计划时间 | T-1 场景（今天用昨天的数据） |
| **虚拟依赖** | 依赖源端实时任务（非周期任务），在任务里新增 URL 类型 job 查数据库判断依赖状态 | 源端是实时任务 |

选择策略：
- 不确定就用**宽依赖**（默认）
- I 视图→F 表、DQ→I 视图：脚本自动补宽依赖，不需要填

---

## 六、step_type / target_role 字段参考

多步骤数据流的核心字段。每个规则声明自己的 step_type 和 target_role，
多步骤间用 produces_for / reads 声明依赖。

### step_type 四种类型

| step_type | 用途 | target_role | 什么时候选 |
|-----------|------|-------------|----------|
| `full` | 单规则直接灌目标（CTE 内联中间逻辑）| target | 简单场景：JOIN 少、无粒度变化、字段加工直接。也用于读中间表装配目标 |
| `aggregate` | 聚合产出物理中间表 | intermediate | 全量复杂场景：命中复杂度阈值（§4.1）且满足物化条件（§4.2） |
| `incremental_extract` | 从源表取增量到临时表 | intermediate | 增量场景：每张驱动表一个，产出各自的 tmp（§5.2） |
| `merge` | 合并临时表/中间表到目标表 | target | 增量合并：读 extract 步骤的 tmp，MERGE/分区删插到目标（§5.2） |

> 简单全量资产只有一个 `full` 规则（走老路），不涉及中间表和依赖声明。

### target_role

| target_role | 含义 | 生命周期 |
|-------------|------|---------|
| `intermediate` | 中间表/临时表（供后续规则消费）| 每次重建（truncate 后灌，用完即丢）|
| `target` | 目标 F 表（最终产出）| 按 load_mode 管理 |

### produces_for / reads（步骤间依赖）

多步骤数据流用这两个字段声明依赖（与 `data_flow.dependencies` 互补）：

- `produces_for`: 本规则产出的中间表供哪些规则消费（rule_code 列表）
- `reads`: 本规则读取哪些中间表（表名列表）

示例（全量复杂宽表 order_center 模式）：
```
R0001: aggregate  → tmp1  (target_role=intermediate, produces_for=[R0003])
R0002: aggregate  → tmp2  (target_role=intermediate, produces_for=[R0003])
R0003: full       → 目标表 (target_role=target, reads=[tmp1,tmp2])
```

示例（多源增量）：
```
R0001: incremental_extract → tmp_a (target_role=intermediate, produces_for=[R0003], incremental={key:update_time,...})
R0002: incremental_extract → tmp_b (target_role=intermediate, produces_for=[R0003], incremental={key:dt,...})
R0003: merge → 目标表 (target_role=target, reads=[tmp_a,tmp_b], load_mode=merge_into, merge_key=business_key)
```

### 对应的产出字段

| 字段 | 在哪声明 | ts-template 位置 |
|------|---------|-----------------|
| `step_type` | design_decisions.rules[].step_type | rules.{code}.step_type |
| `target_role` | design_decisions.rules[].target_role | rules.{code}.target_role |
| `produces_for` | design_decisions.rules[].produces_for | rules.{code}.produces_for |
| `reads` | design_decisions.rules[].reads | rules.{code}.reads |
| `incremental` | design_decisions.rules[].incremental | rules.{code}.incremental（extract 步骤填）|

> assemble_ts.py 从 design_decisions 搬这些字段进 ts.json。designer 只在 design_decisions 填，不直接写 ts.json。
