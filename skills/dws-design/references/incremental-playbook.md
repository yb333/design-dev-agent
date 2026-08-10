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

### ★ 核心铁律：凡进驱动表清单的，变化都要抓

> 凡是 RS 标进"增量驱动表"清单的表，**它的任何变化都必须能被增量范围覆盖**。
> 因为每张驱动表的字段都可能落到目标字段上——哪怕是所谓的"从表"，它的金额/状态变了，
> 对应目标行的那个字段就是旧的，数据错误。
>
> **驱动表之间没有主次之分，都是变化源。** 漏了任一张的变化 = 目标数据错误。

### 三种增量模式（按"增量范围怎么算"选）

增量设计的关键不是"几个规则"，而是**增量范围怎么确定**。决策主轴：多张驱动表的变化，是各自独立进目标，还是 JOIN 进同一行要并集重建？

**模式一：单驱动表**

只有一张驱动表，增量范围 = 该表的增量条件。

```
驱动表A（按 update_time 取增量）→ 目标表  [一个 incremental 规则]
WHERE A.update_time >= ${BIZ_DATE_START} AND A.update_time < ${BIZ_DATE_END}
```

适用：只一张表的变化要抓。

**模式二：多源独立取增量（每张一个 extract → merge）**

多张驱动表各自独立写进目标（union 累积），互不影响。增量范围 = 各自各自的 delta。

```
驱动表A（按 update_time）→ 临时表 tmp_a  [incremental_extract]
驱动表B（按 dt）         → 临时表 tmp_b  [incremental_extract]
tmp_a + tmp_b → MERGE 合并 → 目标表       [merge]
```

适用：多来源 union / 累积共建场景（见 §三 accumulate 模式）。每张表一个 extract 规则，产出各自物理临时表（每次重建），最后 merge。

**模式三：并集影响范围（多表 JOIN 进同一行，任一表变都要重建）★ 最易出错**

多张驱动表 JOIN 进同一目标行，**任一张表变化都要重建该目标行**。增量范围 = 所有驱动表变化的**并集**。

```
驱动表A + 驱动表B JOIN 进同一目标行
增量范围 = A 变化的行 ∪ B 变化的行
用这个并集范围 JOIN 所有表，重建受影响的目标行
```

可以用一个规则搞定，关键在于增量范围必须覆盖每张驱动表的变化。两种 SQL 写法（designer 选）：

```sql
-- 写法1：增量条件用 OR 连接（并集体现在 WHERE）
SELECT A.*, B.amount FROM A JOIN B ON A.id = B.a_id
WHERE A.update_time >= ${BIZ_DATE_START}
   OR B.update_time >= ${BIZ_DATE_START}

-- 写法2：先各取 delta 求 union，再用影响集 JOIN 重建
WITH chg AS (
  SELECT id FROM A WHERE A.update_time >= ${BIZ_DATE_START}
  UNION
  SELECT a_id FROM B WHERE B.update_time >= ${BIZ_DATE_START}
)
SELECT A.*, B.amount FROM A JOIN B ON A.id = B.a_id
JOIN chg ON A.id = chg.id
```

适用：多张表 JOIN 进同一目标，字段来自不同表，任一源表变化都影响目标字段值。

> **业界共识**（Stack Overflow 多表 CDC）：load each source's delta independently,
> then rebuild the affected target rows from the **union of all deltas** that touched any contributing source.
> 任一源变了，重建受影响的目标行。

### 模式选择决策表

| 场景 | 增量范围 | 推荐模式 |
|------|---------|---------|
| 只一张表的变化要抓 | 该表的增量条件 | 模式一 |
| 多张表各自独立写进目标（union） | 各自各自的 delta | 模式二（每张一个 extract → merge）|
| 多张表 JOIN 进同一行，任一表变都影响目标 | 各驱动表变化的**并集** | 模式三（一个规则，并集范围重建）|

### ★ 防臆想（校验兜底 + 闸口①人确认）

最易出错的是：**漏掉某张驱动表的变化**。比如模式三里只写了 A 的增量条件、忘了 OR B 的条件 → B 变化的行没进增量范围 → 目标字段用了旧值。

- assemble_ts 会校验"资产标了增量但完全没增量处理"（无 extract、无 incremental 段、source 不涉驱动表）→ 硬阻断兜底。
- 但"增量范围里漏了某张驱动表的条件"是语义判断（取决于该表字段是否落到目标），校验做不到——**由 designer 保证 + 闸口①人确认**。warn 会提示"确认每张驱动表的增量变化已被增量范围覆盖"。

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

## 五、关于校验（不限制设计模式）

assemble_ts 的增量校验**只兜底线，不规定用哪种模式**：
- **硬阻断**：资产标了增量但完全没增量处理（无 extract 规则、无 incremental 段、规则的 source 不涉及任何驱动表）→ 这是"完全没管增量"的铁证。
- **warn**：某张驱动表的增量字段未在增量条件里出现 → 提示"确认这张驱动表的变化已被增量范围覆盖"（语义判断，由 designer + 闸口①保证）。

至于用模式一/二/三、几个规则、extract 数和驱动表数是否相等——**都是 designer 的设计自由，校验不限制**。extract 数可以小于驱动表数（模式三一个规则搞定），也可以等于（模式二），甚至一张表按场景拆多个 extract。

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

---

## 附录：多步骤标准 design_decisions 示例

> designer 从零摸索常出错，这里给两个最常见的多步骤完整示例。
> 关键认知：**装配/merge 步骤的字段从临时表搬运，默认直取，不要求重写 design_logic**（加工逻辑在前序步骤已完成）。

### 示例一：增量 extract → merge（模式二）

两张驱动表各自取增量到临时表，merge 合并到目标。R0003（merge）的字段从 tmp 搬运，不写 field_logics。

```yaml
rules:
  # R0001：驱动表A 取增量到临时表（加工在这一步完成）
  - rule_code: R0001
    rule_name: "订单增量取数"
    scenario: "default"
    exec_sequence: 1
    target_table: "dws.tmp_order_a"           # 临时表（intermediate）
    step_type: incremental_extract
    target_role: intermediate
    produces_for: ["R0003"]                   # 产出供 merge 步骤消费
    reads: []
    incremental:
      key: "update_time"
      filter: "update_time >= '${BIZ_DATE_START}' AND update_time < '${BIZ_DATE_END}'"
      init_filter: "1=1"
      init_time_range: "ALL"
      init_strategy: "首次全量加载，后续按 update_time 增量"
      init_mode: "参数控制"
    field_targets: [order_id, order_amt, order_dt]  # 这些字段的加工逻辑在这一步写
    field_logics:
      order_amt: "订单本币金额，取已确认状态金额"     # ★ 加工字段在 extract 步骤写 logic
    load_mode: truncate_table                 # 临时表每次重建

  # R0002：驱动表B 取增量到临时表（同上，不同驱动表）
  - rule_code: R0002
    rule_name: "支付增量取数"
    scenario: "default"
    exec_sequence: 2
    target_table: "dws.tmp_pay_b"
    step_type: incremental_extract
    target_role: intermediate
    produces_for: ["R0003"]
    reads: []
    incremental:
      key: "dt"
      filter: "dt >= '${BIZ_DATE_START}' AND dt < '${BIZ_DATE_END}'"
      init_filter: "1=1"
      init_time_range: "ALL"
      init_strategy: "首次全量加载，后续按 dt 增量"
      init_mode: "参数控制"
    field_targets: [pay_amt]
    field_logics:
      pay_amt: "支付金额，取已支付状态汇总"
    load_mode: truncate_table

  # R0003：merge 合并到目标（纯搬运，字段从 tmp 取，不写 field_logics）
  - rule_code: R0003
    rule_name: "合并到目标表"
    scenario: "default"
    exec_sequence: 3
    target_table: "dws.dwb_order_f"           # 最终目标表
    step_type: merge
    target_role: target
    produces_for: []
    reads: ["dws.tmp_order_a", "dws.tmp_pay_b"]  # ★ 读两张临时表
    load_mode: merge_into
    write_condition: "T.order_id=T1.order_id"     # MERGE ON 条件
    field_targets: [order_id, order_amt, order_dt, pay_amt, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    field_logics: {}                            # ★ 留空：字段从前序步骤搬过来，默认直取
    grain: {input: "一行=一个订单", output: "一行=一个订单", change: "无变化"}

params:
  - {name: "BIZ_DATE_START", value_type: "date", desc: "增量起始业务日期"}
  - {name: "BIZ_DATE_END", value_type: "date", desc: "增量结束业务日期"}

business_key: [order_id]
business_key_design:
  input_key: [order_id]
  adjusted: false
  reason: "沿用输入主键，产出粒度未变"

schedule:
  schedule_type: daily
  cron: "0 30 3 * * ?"
```

### 示例二：全量 aggregate → 装配（复杂宽表拆步骤）

两张维度各自聚合到临时表，最终 full 装配到目标。R0003（装配）的字段从 tmp 搬运。

```yaml
rules:
  - rule_code: R0001
    rule_name: "用户维度聚合"
    exec_sequence: 1
    target_table: "dws.tmp_user_dim"
    step_type: aggregate                       # 聚合产出中间表
    target_role: intermediate
    produces_for: ["R0003"]
    field_targets: [user_id, fav_pay_method, user_level]
    field_logics:
      fav_pay_method: "取近30天最常用支付方式"
      user_level: "按累计消费金额分级"
    load_mode: truncate_table

  - rule_code: R0002
    rule_name: "商品维度聚合"
    exec_sequence: 2
    target_table: "dws.tmp_prod_dim"
    step_type: aggregate
    target_role: intermediate
    produces_for: ["R0003"]
    field_targets: [product_id, product_sales_cnt, product_cat]
    field_logics:
      product_sales_cnt: "近30天销量汇总"
    load_mode: truncate_table

  # R0003：装配目标（从两张 tmp 搬运 + 关联源表取直取字段）
  - rule_code: R0003
    rule_name: "装配宽表"
    exec_sequence: 3
    target_table: "dws.dwb_order_product_f"
    step_type: full
    target_role: target
    reads: ["dws.tmp_user_dim", "dws.tmp_prod_dim"]   # ★ 读两张中间表
    field_targets: [order_id, user_id, product_id, fav_pay_method, user_level, product_sales_cnt, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]
    field_logics: {}   # ★ 留空：加工字段从前序步骤搬，直取字段脚本自动填
    grain: {input: "一行=一个订单商品", output: "一行=一个订单商品", change: "无变化"}
    load_mode: truncate_table

business_key: [order_id, product_id]
business_key_design:
  input_key: [order_id]
  adjusted: true
  reason: "头行整合后头表主键 order_id 发散，补 product_id 行字段"
```

### 两个示例的关键规律

1. **加工逻辑只在"做加工的步骤"写**——extract/aggregate 步骤写 field_logics，装配/merge 步骤留空
2. **装配/merge 步骤必须声明 reads**——告诉脚本从哪些临时表搬（脚本据此构建 source_tables + 判定字段为直取）
3. **produces_for / reads 双向声明依赖**——中间表填 produces_for，装配/merge 填 reads
4. **临时表 load_mode 是 truncate_table**（每次重建）；目标表看增量/全量定
