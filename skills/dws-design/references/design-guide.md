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

## 四、分段决策（复杂度评估）

designer 评估复杂度后决定**是否分段、是否建中间表**。

### 4.1 触发分段的指标

| 指标 | 阈值 | 说明 |
|------|------|------|
| JOIN 表数量 | > 12 | 关联表过多，单条 INSERT 难以一次写对 |
| 多步骤加工字段数 | ≥ 5 | 多个字段需要先聚合再关联、先拆再拼 |
| 粒度变化 | 有即声明 | 输入输出粒度不一致（聚合/展开） |
| 聚合后关联 | 有 | 先 GROUP BY 再 JOIN，逻辑复杂 |
| 复杂关联链 | ≥ 3 层 | A→B→C 串联依赖 |

### 4.2 分段决策

- **不分段**：JOIN 少、无粒度变化、字段加工直接 → 单条规则搞定
- **分段**：命中阈值 → 拆成多个规则（中间表收口）

**中间表 vs CTE 决策**：
- 中间表能复用、能独立校验 → 建物理中间表
- 只在本规则内用一次、无需独立校验 → 用 CTE 内联
- 中间表粒度 = 它收口后的输出粒度（不是源粒度）

### 4.3 螺旋式中间表设计

中间表设计是螺旋的——先骨架后回填：
1. **先骨架**：复杂度评估后决定建几个中间表，定表名/粒度/用途
2. **字段逻辑**：确定每个字段加工逻辑时，识别哪些字段落在中间表
3. **回填字段**：从字段分配回填出每个中间表的完整字段清单

> 中间表的字段绝大多数与目标表字段同名同类型（透传/聚合），极少量 designer 自建字段（辅助计算中间产物）。中间表统一加审计字段。

## 五、调度设计

### 5.1 调度类型

从 RS L07 的调度频率推导 `schedule_type`：

| RS L07 调度频率 | schedule_type | 说明 |
|----------------|---------------|------|
| T+1、一天一调、日调度 | `daily` | 最常见 |
| 一天多调、小时级 | `hourly` | 高频周期 |
| 分钟级、准实时 | `realtime` | 高频周期（俗称实时） |

### 5.2 增量设计

当 RS L07 的"增量识别方式"不是"不涉及"时，该资产为增量场景。增量是规则级的——同一资产里有的规则全量、有的增量。

#### 增量识别方式

| 识别方式 | 说明 | 示例 |
|---------|------|------|
| **时间戳字段** | 源表有 update_time，按时间范围过滤 | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| **分区字段** | 源表有日期分区，按分区读取 | `dt >= '${BIZ_DATE_START}' AND dt < '${BIZ_DATE_END}'` |

#### 增量写入方式（load_mode）

| load_mode | 说明 | 典型场景 |
|-----------|------|---------|
| `truncate_partition` | 按分区清空再插 | 分区日增量（清当天分区再灌） |
| `no_delete` | 直接追加 | 事件流水（只加不改） |
| `delete` | 按条件删后插 | 可能有数据修正的表（删当天再插） |
| `merge_into` | Upsert | 维度表（有更新有新增） |

#### 增量参数

增量过滤用**起止双参数**：
- `BIZ_DATE_START`：增量起始日期
- `BIZ_DATE_END`：增量结束日期

在 `params` 段声明，在 `lts_params` 段配置 LTS 侧变量赋值（如 `V_BIZ_DATE_START → BIZ_DATE_START`）。

#### 初始化设计

初始化和增量是**同一套规则、WHERE 不同**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `incremental.filter` | 增量 WHERE | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| `incremental.init_filter` | 初始化 WHERE | `1=1`（全量）或 `dt >= '2024-01-01'`（限定范围） |
| `incremental.init_time_range` | 初始化时间范围（RS L07） | ALL / 2024-01-01 |
| `incremental.init_strategy` | 初始化策略描述 | 首次全量加载，后续增量 |

> 初始化在术加平台通过"参数控制"（同规则组传不同参数）或"独立规则组"（复制一套规则组）实现。
> ts.json 只设计一套规则 + init_filter，具体实现方式由部署决定。

#### 增量场景矩阵

| 场景 | 识别 | 写入 | filter 示例 | init_filter |
|------|------|------|------------|-------------|
| 分区日增量 | 分区字段 | truncate_partition | `dt >= '${BIZ_DATE_START}' AND dt < '${BIZ_DATE_END}'` | `1=1` |
| 时间戳追加 | 时间戳 | no_delete | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` | `1=1` |
| 时间戳重刷 | 时间戳 | delete | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` | `1=1` |
| Upsert增量 | 时间戳 | merge_into | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` | `1=1` |

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
