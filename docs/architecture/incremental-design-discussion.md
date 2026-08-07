# 多步骤数据流设计与 ts 规则模型讨论（全量+增量统一）

> 状态：**讨论中，未定方案**。本文档沉淀诊断和候选方向，供反复审视补充。
> 起因：增量场景的设计方式"低级死板"。深入后发现根因不在增量，在 ts 规则模型对"多步骤数据流"的表达能力——全量复杂场景和增量场景面临的是同一个结构问题。

---

## 〇、核心结论：全量和增量是同一个问题

**两类场景，同一个结构诉求**：

| 场景 | 触发原因 | 数据流模式 |
|------|---------|----------|
| 全量复杂宽表 | 多源 JOIN 太复杂，先聚合中间表再装配 | tmp1/tmp2 → 装配目标表 |
| 增量 | 多驱动表各自取增量再合并 | tmp_a/tmp_b → MERGE 目标表 |

共同诉求：多个中间步骤各自产出 tmp → 最终步骤读 tmp 装配/合并到目标 → 步骤间有显式依赖。

**好消息**：真实产出 order_center（全量）已用 tmp1/tmp2→R0003 模式，且 `data_flow.dependencies` 已显式表达规则间依赖。全量复杂场景的框架**比增量更接近可用**。

**因此本文档讨论的"多步骤数据流"方案（方向A）同时服务全量和增量**——简单场景（单 rule 直接灌目标，不论全量增量）都不受影响，走老路。

---

## 一、问题是怎么暴露的

当前 designer 的增量设计（design-guide.md §5.2）本质是**单表单规则的 WHERE 过滤**：

```
增量 = 同一套 SELECT + WHERE 换成增量过滤条件
初始化 = 同一套 SELECT + WHERE 换成 1=1
```

这套逻辑的隐含假设：**增量数据从一张源表过滤出来，直接 INSERT 到目标表**。

但真实复杂增量场景（如宽表多源增量）是这样的：

```
源表A 按增量范围取数 → 临时表 tmp_a
源表B 按增量范围取数 → 临时表 tmp_b
tmp_a + tmp_b → MERGE 合并 → 目标表
```

这个模式有三个现在框架表达不了的环节：
1. **多源各自取增量**：每张源表各有各的增量范围（A 按 update_time，B 按 dt 分区）
2. **临时表中转**：增量数据先落地 tmp，不在一条 SELECT 里直接 JOIN
3. **MERGE 更新目标**：不是 truncate/insert，是 upsert 合并

---

## 二、根因：ts 规则模型的三个硬卡点

当前 ts-template.json 的 rules 结构：**"一条规则 = 一条 INSERT = 产出一个表"**。
注释明确写了 `target_table` 是"产出表(中间表/目标F表/视图I表)"。这个假设对简单场景成立，但到复杂场景卡在三点：

### 卡点 1：一个 rule 只有一个 target_table

多源增量需要"产出 tmp_a、tmp_b、再产出目标表"——三个独立产出。
现在压成一个 rule 不行，只能拆成三个 rule（R0001→tmp_a、R0002→tmp_b、R0003→目标）。
但三个 rule 之间的依赖（R0003 读 tmp_a/tmp_b）**没有显式表达**，只靠 exec_sequence 数字隐式排序。

### 卡点 2：跨规则依赖靠 exec_sequence 隐式保证

真实产出 dwb_order_center_f（**全量**场景）已经用了这个模式（3 条规则链式）：
- R0001 → tmp1（聚合用户订单指标）
- R0002 → tmp2（聚合商品销量）
- R0003 → 目标表（JOIN tmp1/tmp2 装配，18 张源表）

**而且 `data_flow.dependencies` 已显式表达了依赖**（R0001→R0003 经 tmp1，R0002→R0003 经 tmp2）。
但有两个缺口：
1. tmp 表没有 `target_role=intermediate` 标记（靠命名约定"tmp"猜，不严谨）
2. coder 切片单规则时不直接消费 dependencies（拿 R0003 切片时，要自己从 dependencies 推断 tmp 来自哪个 rule）

### 卡点 3：load_mode 是目标表级的，无法区分步骤

增量场景里：
- "取增量到 tmp"：load_mode = truncate_table（tmp 每次重建）
- "MERGE 到目标"：load_mode = merge_into（增量合并）

这是两个不同的写入方式，但一个 rule 只能有一个 load_mode。
现在只能拆成两个 rule，但两者的"增量范围"是同一个（同一批增量数据），拆开后增量参数要重复声明。

---

## 三、现在框架其实有"半成品"中间表能力

看真实产出，中间表模式**在实践中已经在用**，只是没显式建模：

| 已有能力 | 在哪 | 缺什么 |
|---------|------|--------|
| `target_table` 支持中间表 | ts-template:148 注释含"中间表" | 中间表和目标表无区分标记 |
| `ctes` 内联临时表 | ts-template:157 | 只能单 rule 内的 CTE，不能跨 rule 复用 |
| `exec_sequence` 顺序 | ts-template:147 | 只是数字，不表达数据依赖 |
| `data_flow.dependencies` | ts-template:198 | 有 from/to 但没用于执行编排 |

**结论**：不是要从零造，而是把已有零件组合成显式的"多步骤数据流编排"能力。

---

## 四、候选方向（未定，列取舍供讨论）

### 方向 A：最小改动——给 rule 加"步骤类型"标记

在现有 rule 上加字段，不破坏"一条规则=一个表"：

```json
"R0001": {
  "step_type": "incremental_extract",  // 新增：full | incremental_extract | merge_target
  "target_table": "tmp_a",
  "target_role": "intermediate",       // 新增：intermediate | target
  "incremental": { ... },              // 增量提取的来源/范围
  "produces_for": ["R0003"]            // 新增：本步骤产出供哪些步骤消费
}
```

- **优点**：改动小，现有简单规则不动（step_type=full 走老路）
- **缺点**：produces_for 是新依赖机制，要改 coder 切片逻辑（知道 tmp 来自哪个 rule）

### 方向 B：中等改动——rule 内支持多步骤

一条 rule 内部可以声明多个步骤，最终产出一个表：

```json
"R0001": {
  "steps": [
    {"name": "extract_a", "produces": "tmp_a", "incremental": {...}},
    {"name": "extract_b", "produces": "tmp_b", "incremental": {...}},
    {"name": "merge", "reads": ["tmp_a","tmp_b"], "load_mode": "merge_into"}
  ],
  "target_table": "目标表"
}
```

- **优点**：一个资产的数据流在一个 rule 内完整表达，coder 看全貌
- **缺点**：rule 结构变复杂，简单场景也被迫声明 steps（除非 steps 可选）

### 方向 C：大改——规则模型重构为 DAG

把 rules 从"顺序列表"改为"有向无环图"，每个节点是一个数据加工步骤：

```json
"flow": {
  "nodes": [
    {"id":"ext_a","type":"incremental_extract","source":"表A","produces":"tmp_a"},
    {"id":"ext_b","type":"incremental_extract","source":"表B","produces":"tmp_b"},
    {"id":"merge","type":"merge","reads":["tmp_a","tmp_b"],"target":"目标表"}
  ],
  "edges": [["ext_a","merge"],["ext_b","merge"]]
}
```

- **优点**：最通用，任意复杂的数据流都能表达
- **缺点**：大改，现有所有脚本（assemble_ts/coder/UT/export）全要适配，风险高

---

## 五、核心取舍（待讨论定夺）

### 取舍 1：简单场景要不要"向上兼容"

- 现在框架对简单全量场景（占多数）足够且简单
- 任何改动都不应强迫简单场景走复杂的多步骤编排
- **倾向**：新能力是"可选叠加"，简单规则保持现状

### 取舍 2：中间表是 rule 级还是 rule 内

- rule 级（方向A）：一个中间表一个 rule，靠依赖关系串联。已有实践（order_center 已这么用）
- rule 内（方向B）：中间表是 rule 的内部步骤，一个 rule 含完整数据流
- **倾向**：rule 级更符合现有结构，改动小

### 取舍 3：增量设计方法论的彻底程度

- 只补临时表环节：最小改动，但多源增量仍难表达
- 重写增量方法论：支持多源增量→临时表→MERGE，但 ts 结构要动
- **倾向**：看方向选择再定

---

## 六、不在本文档讨论范围

- 试算 SQL / 调度路径 / 单元测试补缺（已在闲时任务里，独立推进）
- coder 怎么翻译多步骤规则（方向定了再讨论 coder 适配）
- UT 怎么验证中间表链（方向定了再讨论 UT 适配）

---

## 六、不在本文档讨论范围

- 试算 SQL / 调度路径 / 单元测试补缺（已在闲时任务里，独立推进）
- coder 怎么翻译多步骤规则（方向定了再讨论 coder 适配）
- UT 怎么验证中间表链（方向定了再讨论 UT 适配）

---

## 七、业界调研结论（三篇权威资料一致）

读了 Skyvia 增量指南、Databricks CDC、Microsoft Fabric，核心共识：

1. **"临时表 + MERGE" 是业界共识，非特例**。源表取增量 → staging/temp table（中转）→ MERGE 目标表。原因：可验证可回滚、幂等、性能。
2. **增量识别四种策略，按源表能力各选各的**：Watermark（水位线）、CDC（变更捕获）、Trigger、快照对比。多源增量是各自独立管道（modular pipelines），不是一条大 SQL。
3. **初始化和增量统一**：同一套逻辑，数据范围不同（Databricks 框架级支持）。
4. **SCD1（覆盖）够用，SCD2（版本化）暂不需要**。

我们当前只有 Watermark（水位线）和分区两种，无 CDC。够用。

### 补充调研：CTE vs 物理临时表的决策标准（Brent Ozar + Microsoft 官方）

业界对"何时该把中间结果物化成物理临时表（而非用 CTE 内联）"有明确共识：
**"Start with CTE, materialize to temp table when needed"**（从 CTE 开始，必要时物化）。

| 判断维度 | CTE 够用 | 必须物化成物理临时表 |
|---------|---------|-------------------|
| 中间结果引用次数 | 只用一次 | **多次引用**（重算浪费）|
| 行估算准确性 | 优化器估算准 | **估算偏差 >10x**（误差放大致性能崩）|
| 数据量 | 小 | **大**（需索引加速 JOIN）|
| 可调试性 | 不需检查中间数据 | **需要检查点**（排查问题）|
| 跨步骤传递 | 单条 SQL 内 | **跨步骤**（ETL 多阶段）|

**对 ETL/数据仓库的关键结论**（Microsoft 官方 + Brent Ozar 真实案例）：
- Microsoft 官方明确把临时表机制类比为"简单的 ETL 过程"
- 真实案例：CTE 重的过程 90 分钟 → 改索引临时表后 **15 秒**
- **多步骤 ETL 天然适合物理临时表**：每步产出可检查、可复用、可索引

**对 designer 决策的指导**：
- 简单场景（单表直灌、少 JOIN）→ CTE 够，不拆（step_type=full 走老路）
- 复杂宽表（多源 JOIN、中间结果多次引用、聚合后关联）→ **应拆物理临时表**（step_type=aggregate，性能+可调试）
- 多源增量 → **必须拆**（各源各自增量范围，CTE 表达不了）

这是我们之前自己构造的案例没说清的——拆物理临时表不是风格偏好，是有性能和可维护性依据的工程决策。

---

## 八、实践确认（与业务方对齐）

- [x] **增量占比**：增量全量各半，两者都要好好支持，不偏废
- [x] **增量识别**：水位线（update_time）+ 分区（dt）为主，无 CDC。**RS 会给增量要求（驱动表、增量条件），但当前没规范到这一层**——L07 只到资产级，缺规则级/表级的驱动表+增量条件
- [x] **驱动表机制**：**多驱动表（各自独立增量）**，不是单主表驱动。每张驱动表各自有增量范围
- [x] **临时表生命周期**：**物理临时表，每次重建（用完即丢）**，不用 CTE 内联（多源各自增量范围不同，CTE 搞不定）
- [x] **合并方式**：**看表类型和增量类型**——一般增量用 MERGE（upsert）；会计期/分区类用分区 truncate+insert。不固定一种
- [x] **MERGE key**：复用 **business_key**

### 标准增量数据流（对齐后）

```
[RS L07] 增量识别 + 驱动表 + 增量条件（★ 当前缺规范，要补）
    ↓
[多驱动表各自取增量]  每张驱动表各自增量范围（水位线/分区）
    ↓
[物理临时表（每次重建）]  各驱动表增量 → 各自 tmp（truncate 重建）
    ↓
[合并到目标表]  按 load_mode：
    - 一般增量 → MERGE（upsert，key=business_key）
    - 会计期/分区 → 分区 truncate + insert
    ↓
[初始化]  同一套逻辑，范围换全量/初始范围
```

---

## 九、推荐方向（基于调研+实践，收敛自方向A）

方向 A/B/C 中，**A（最小改动：rule 加步骤标记）最适合**，理由：
- 增量全量各半 → 不能强迫全量走复杂编排，A 让简单规则不动（step_type=full 走老路）
- 多驱动表 → 每个驱动表一个 rule（extract 步骤），天然模块化，符合业界"各自独立管道"
- 物理临时表每次重建 → tmp 表就是一个 rule 的 target（target_role=intermediate），已有结构能载
- coder/UT 适配改动可控 → 加 produces_for 依赖标记，切片时知道 tmp 来自哪个 rule
- **全量复杂场景同样受益**：order_center 已用 tmp1/tmp2→R0003，加 target_role 后从"靠命名猜"变"显式标记"

### 全量复杂场景的 rule 编排（示例）

以 order_center 为例（全量，多源 JOIN 太复杂先聚合再装配）：

```
R0001: aggregate_user  → tmp1  (target_role=intermediate, produces_for=[R0003])
R0002: aggregate_product → tmp2 (target_role=intermediate, produces_for=[R0003])
R0003: assemble        → 目标表 (reads=[tmp1,tmp2], target_role=target, step_type=full)
```

与现在的区别：tmp 表有 target_role=intermediate 显式标记（不再靠"tmp"命名猜），coder 拿 R0003 切片时能从 produces_for/dependencies 直接知道 tmp1/tmp2 来自哪个 rule。

### 增量场景的 rule 编排（示例）

假设资产 dwb_xxx_f，两驱动表（A 按 update_time 增量、B 按 dt 分区增量）：

```
R0001: extract_a  → tmp_a   (target_role=intermediate, step_type=incremental_extract, incremental={key:update_time, filter:...}, produces_for=[R0003])
R0002: extract_b  → tmp_b   (target_role=intermediate, step_type=incremental_extract, incremental={key:dt, filter:...}, produces_for=[R0003])
R0003: merge      → 目标表  (reads=[tmp_a,tmp_b], target_role=target, step_type=merge, load_mode=merge_into, merge_key=business_key)
```

### 两类场景的 step_type 对照

| step_type | 全量用 | 增量用 | target_role |
|-----------|--------|--------|-------------|
| `full` | ✅ 单 rule 直接灌目标（简单全量）| | target |
| `aggregate` | ✅ 聚合中间表（复杂全量装配）| | intermediate |
| `incremental_extract` | | ✅ 增量取数到 tmp | intermediate |
| `merge` | | ✅ MERGE 合并到目标 | target |

简单场景（全量单 rule）不受影响：step_type=full 走现有老路。

### 要补的 RS 规范（关键缺口）

RS L07 当前只到资产级（增量识别方式），缺**规则级/表级的驱动表+增量条件**。需要规范：
- 哪张表是增量驱动表
- 该表的增量识别方式（水位线字段 / 分区字段）
- 增量条件表达式
- 是否多驱动表（各自的增量范围）

---

## 十、待决（落地进度跟踪）

- [x] RS L07 驱动表/增量条件规范（RS 模板已补"增量表及增量字段"段；preprocess 解析 → 闲时任务已落地）
- [x] step_type / target_role / produces_for / reads 字段定义进 ts-template + design-decisions-template（已加，含注释）
- [x] designer.md / design-guide / SKILL.md 引导做增量设计（三层已填充，design-guide §4.4/§5.2）
- [x] assemble_ts 组装 step_type 等新字段进 ts.json（闲时任务已落地）
- [x] preprocess 解析 RS 增量表段进 rs_input.json（闲时任务已落地）
- [ ] **write_condition 字段承载**（load_mode 的写入条件：MERGE ON / partition 分区名 / delete WHERE）
  → 方案已定（见 §十一），待落地
- [ ] run_ut 的 wrap_insert 扩展为 wrap_write（按 load_mode 拼 INSERT/MERGE/PARTITION/DELETE）
  → 依赖 write_condition，待落地
- [ ] assemble_export 删除模式从 ts.json load_mode 读（不再硬编码 "1"）
  → 依赖 write_condition，待落地
- [ ] coder 按 step_type 产 SELECT（extract 加增量 WHERE、merge 读 tmp）+ etl-templates 补模板
  → 待落地

---

## 十一、write_condition 设计方案（已定，待落地）

### 核心决策：统一 designer 填，不做推导

写入条件（MERGE ON / partition 分区名 / delete WHERE）**全部由 designer 声明**，
assemble_ts 只搬运不推导。理由：复杂的能填对，简单的更不在话下；半推导半手填
增加系统复杂度（推导逻辑+覆盖合并+边界处理），不如统一手填+输出校验。

### 平台写入配置规范

| load_mode | delete_mode | write_condition 填什么 | designer 填 |
|-----------|------------|----------------------|------------|
| truncate_table | 1 | 空 | 不用填 |
| no_delete | 2 | 空 | 不用填 |
| truncate_partition | 5 | 分区名（如 `P_1001`）| ✅ 填 |
| delete | 4 | delete 的 WHERE（如 `rule_id>0`，目标表别名 `T`）| ✅ 填 |
| merge_into | 6 | ON 条件（如 `T.id=T1.id`，T=目标表 T1=源）| ✅ 填 |
| update | (类似merge) | ON 条件 | ✅ 填 |

约定：目标表别名固定 `T`，源（SELECT 结果）别名 `T1`。

### 校验规则（assemble_ts 输出时）

- load_mode ∈ {truncate_partition/delete/merge_into/update} 时，write_condition 不能为空
- write_condition 不能含中文（必须是 SQL 片段）
- truncate_partition 的 write_condition 应像分区名（字母数字下划线，不确认就只校验非空+非中文）

### 改动清单（六处）

1. **ts-template + design-decisions-template**：rule 加 write_condition 字段
2. **assemble_ts build_rule**：搬 write_condition（只搬运不推导）+ 输出校验（非空/非中文）
3. **run_ut.py**：wrap_insert 扩展为 wrap_write（按 load_mode+write_condition 拼 INSERT/MERGE/PARTITION/DELETE）
4. **ut_execute.py**：预处理按 load_mode 分流（merge 不预处理、partition 加 TRUNCATE PARTITION）
5. **assemble_export.py**：删除模式从 load_mode 映射（不再硬编码 "1"），write_condition 填删除条件列
6. **coder.md + etl-templates.md**：extract 的 SELECT 加增量 WHERE、merge 的 SELECT 读 tmp 产出结果集

---

*闲时任务全部完成。剩余 write_condition 承载 + run_ut/export/coder 适配待落地。*
