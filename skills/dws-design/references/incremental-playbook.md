# 增量设计 Playbook

> 命中条件：RS 标了增量（L07 增量识别方式 ≠ "不涉及"），或 designer 判断该资产为增量场景时读本文。
> 自包含：增量涉及的所有判断（含中间表物化、累积共建、排重）都在本文内，不跳外部。

---

## 一、增量识别（从 RS 读）

RS L07 的"增量表及增量字段"段给出**驱动表 + 增量字段**。一张资产可能有多个驱动表。

| 识别方式 | 说明 | 示例 |
|---------|------|------|
| **水位线（时间戳）** | 源表有 update_time，按时间范围过滤 | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| **分区字段** | 源表有日期分区，按分区读取 | `dt >= '${BIZ_DATE_START}' AND dt < '${BIZ_DATE_END}'` |

**核心认知**：增量是"每条数据路径的属性"，不是"整张表的属性"。多张驱动表 = 多条独立的数据路径，各自有增量范围。

---

## 二、多驱动表数据流（标准模式）

> 业界共识（Skyvia / Databricks / Microsoft Fabric）：增量加载的标准模式是
> "源表取增量 → 临时表（staging）中转 → MERGE 合并到目标表"。临时表中转的原因：
> 可验证可回滚、幂等（重跑不重复）、性能（MERGE 在临时表和目标表间做比边查边写快）。

### 标准数据流

```
驱动表A（按 update_time 取增量）→ 临时表 tmp_a  [step_type=incremental_extract]
驱动表B（按 dt 取增量）         → 临时表 tmp_b  [step_type=incremental_extract]
tmp_a + tmp_b → MERGE 合并      → 目标表        [step_type=merge]
```

- 每个驱动表一个 `incremental_extract` 规则，产出各自的物理临时表（target_role=intermediate）
- 临时表**每次重建**（先 truncate 再灌，用完即丢——业界 staging 模式）
- 最终一个 `merge` 规则读临时表 + 必要维表，合并到目标表

### ★ 多驱动表逐表对账（校验兜底，防臆想）

**这是最易出错的地方**：designer 容易臆想"主从表关系，只做主表增量即可"。这是错的——**每张驱动表都必须有对应的 extract 步骤**，否则该来源的增量数据会丢。

assemble_ts 会做硬校验：
- `驱动表数 ≤ extract 规则数`（漏做必拦）
- 每张驱动表的增量字段至少被一个 extract 覆盖（默认拦，合并场景可填豁免 reason 放行，见 §五）

---

## 三、中间表的两种产出模式（★ 累积共建）

中间表（target_role=intermediate）有两种产出方式，靠 `tables.{表}.build_mode` 显式声明：

### 模式一：transform（单一规则一次性产出，默认）

```
规则1：源表 → 加工 → 写入临时表a（完整字段、一次成型）
规则3：读临时表a → 目标表
```

- 临时表由**一个规则**产出，字段完整
- 同表字段不可重复声明（assemble_ts C9 严格校验）

### 模式二：accumulate（多规则累积共建）

真实场景里，多来源系统的字段不对齐，一张临时表常被多个规则累积写入：

**2a. 去重累积（A/B 来源有重叠，需排除已写入的）**

```
规则1：A来源 → 写 10 行到临时表a
规则2：读临时表a 排重 + B来源 → 追加 20 行到临时表a（reads=[临时表a] 自引用）
规则3：读临时表a → 目标表
```

- 临时表被多个规则累积写入（同一批字段，多次写入）
- 规则2 的 reads 含自引用（读自己要写的表，读的是规则1 先写入的数据）
- load_mode 是 no_delete（追加）
- 同表字段可重叠（assemble_ts C9 在 accumulate 模式下放行）

**2b. Union 累积（A/B 来源无重叠，字段或分区拆分）**

```
规则1：A来源 → 写临时表a 的 A 部分字段（如 a/b/c）
规则2：B来源 → 写临时表a 的 B 部分字段（如 b/c/d/e）
规则3：读临时表a 全量 → 目标表
```

- 临时表被多个规则分摊写入（字段集不同，但有重叠也是合法的）
- 无自引用
- 同表字段可重叠（accumulate 模式放行）

### 如何选 build_mode

- 单一规则一次性产出 → `transform`（默认，不用标）
- 多规则共建（无论去重还是 union）→ `accumulate`（必须显式声明，否则 C9 会拦）

---

## 四、排重策略（去重累积场景必填）

### 三层分工

```
输入层（RS/mapping 给）：业务上 A/B 来源有重叠，需要去重（可能给也可能不给去重键）
designer 层（细化落地）：定去重策略——用什么键判断重复、取哪个来源优先
coder 层（实施）：designer 定了策略，coder 翻译成具体 SQL（LEFT JOIN / NOT EXISTS）
```

### dedup_strategy（设计决策，跟 join_safety 并列）

`build_mode=accumulate` 的表，若某规则声明了排重，填 `dedup_strategy`：

```yaml
rules:
  - rule_code: R0002
    dedup_strategy:
      target: "临时表a"            # 对哪张共建表排重
      key: ["order_id"]           # 用什么键判断重复
      priority: "R0001 > R0002"   # 来源优先级（冲突时保留谁）
      reason: "A来源优先于B来源，因为A是主数据"
```

**校验**：声明了 dedup_strategy 的规则，target/key/priority 必填。
**提示**：accumulate 表有字段重叠但没声明 dedup_strategy → warn（确认是否需要排重）。

---

## 五、增量合并到一步（豁免机制）

正常情况一张驱动表一个 extract。但**两张驱动表都按相同增量字段（如同按 dt 分区）**时，合并到一个 extract 是合理的工程优化（减少临时表数量）。

这种情况 `extract 规则数 < 驱动表数`，会触发软阻断。designer 可在 `decisions.exemptions` 填豁免：

```yaml
exemptions:
  - code: "N16"
    target: "ods_payment_f"          # 豁免哪张驱动表
    reason: "两张驱动表同按 dt 分区，合并为一个 extract 取数步骤合理"
```

豁免内容会进 ts.json，闸口①人可见。

---

## 六、合并方式（看表类型选 load_mode）

merge 步骤的 load_mode 取决于目标表的数据修正需求：

| load_mode | 说明 | 典型场景 |
|-----------|------|---------|
| `merge_into` | Upsert（有则更新、无则插入）| 一般增量，MERGE key = business_key |
| `truncate_partition` | 按分区清空再插 | 会计期/分区日增量（清当期/当天分区再灌） |
| `delete` | 按条件删后插 | 可能有数据修正的表（删当期再插） |
| `no_delete` | 直接追加 | 事件流水（只加不改） |

**MERGE key**：复用目标表的 `business_key`（业务主键）。

---

## 七、增量参数

增量过滤用**起止双参数**：
- `BIZ_DATE_START`：增量起始日期
- `BIZ_DATE_END`：增量结束日期

在 `params` 段声明，在 `lts_params` 段配置 LTS 侧变量赋值（如 `V_BIZ_DATE_START → BIZ_DATE_START`）。

assemble_ts 会校验：增量 filter/init_filter 里 `${PARAM}` 引用的参数必须在 params 声明过（防用未声明参数）。

---

## 八、初始化设计

初始化和增量是**同一套数据流、WHERE 不同**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `incremental.filter` | 增量 WHERE | `update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'` |
| `incremental.init_filter` | 初始化 WHERE | `1=1`（全量）或 `dt >= '2024-01-01'`（限定范围） |
| `incremental.init_time_range` | 初始化时间范围（RS L07） | ALL / 2024-01-01 |
| `incremental.init_strategy` | 初始化策略描述 | 首次全量加载，后续增量 |

初始化时，extract 步骤的 WHERE 换成 init_filter（全量或初始范围），merge 步骤的 load_mode 从 merge_into 换成 truncate_table（初始化是全量覆盖）。

### init_mode（designer 必须决策）

初始化在术加平台怎么落地，**是设计决策，不是部署细节**。

**核心判断标准：初始化和增量的差异是不是只在 WHERE？**
- **只在 WHERE 不同** → 参数控制（同一套规则组，WHERE 用条件分支）
- **差异超出 WHERE**（FROM/JOIN/字段处理不同）→ 独立规则组（两套规则各自简洁）

| init_mode | 怎么做 | 什么时候选 |
|-----------|--------|-----------|
| **参数控制** | 同一规则组，传 ALL 或日期参数。SQL 里 WHERE 用条件分支 | 初始化和增量的差异只在 WHERE |
| **独立规则组** | 另建一个规则组，专门跑初始化 | 初始化的加工逻辑跟增量有本质差异 |

---

## 九、增量场景矩阵

| 场景 | 驱动表 | extract step_type | merge load_mode | init_filter |
|------|--------|------------------|----------------|-------------|
| 分区日增量 | 分区表 | incremental_extract | truncate_partition | `1=1` |
| 时间戳追加 | 时间戳表 | incremental_extract | no_delete | `1=1` |
| 时间戳重刷 | 时间戳表 | incremental_extract | delete | `1=1` |
| Upsert增量 | 时间戳表 | incremental_extract | merge_into | `1=1` |
| 多源增量 | 多驱动表 | 多个 incremental_extract | merge_into | `1=1` |
| 多源累积共建 | 多来源 | accumulate 模式共建 tmp | merge_into / no_delete | `1=1` |

---

## 关于 step_type 的说明（避免误解）

> **中间表 ≠ 聚合**。"中间表"（target_role=intermediate）是按"产出供谁消费"定义的，
> 跟它做不做聚合无关。一个中间表可以是聚合产出（step_type=aggregate），
> 也可以是非聚合的加工步骤（step_type=full 但 target_role=intermediate），
> 也可以是增量取数（step_type=incremental_extract）。
> 增量场景的临时表通常是 incremental_extract 产出，不涉及聚合。
> step_type 的完整决策见 complexity-playbook。
