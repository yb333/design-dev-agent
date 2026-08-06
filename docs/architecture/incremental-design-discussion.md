# 增量设计与 ts 规则模型讨论

> 状态：**讨论中，未定方案**。本文档沉淀诊断和候选方向，供反复审视补充。
> 起因：增量场景的设计方式"低级死板"，根因在 ts 规则模型，需扩大讨论范围。

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

真实产出 dwb_order_center_f 已经用了这个模式（3 条规则链式）：
- R0001 → tmp1（聚合用户订单指标）
- R0002 → tmp2（聚合商品销量）
- R0003 → 目标表（JOIN tmp1/tmp2 装配，18 张源表）

但 ts.json 里没有"R0003 依赖 R0001/R0002 的产出"这个显式声明。
coder 拿到 R0003 切片时，要自己推断 tmp1/tmp2 是前序规则的产出。
UT 执行时靠 schedule_groups 的 sequence 保证顺序，但中间表失败不会显式级联。

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
- 物理临时表每次重建 → tmp 表就是一个 rule 的 target（target_role=intermediate），已有结构能承载
- coder/UT 适配改动可控 → 加 produces_for 依赖标记，切片时知道 tmp 来自哪个 rule

### 具体增量场景的 rule 编排（示例）

假设资产 dwb_xxx_f，两驱动表（A 按 update_time 增量、B 按 dt 分区增量）：

```
R0001: extract_a  → tmp_a   (target_role=intermediate, incremental={key:update_time, filter:...}, produces_for=[R0003])
R0002: extract_b  → tmp_b   (target_role=intermediate, incremental={key:dt, filter:...}, produces_for=[R0003])
R0003: merge      → 目标表  (reads=[tmp_a,tmp_b], load_mode=merge_into, merge_key=business_key)
```

全量简单资产不受影响：仍是一个 rule（step_type=full, target_role=target），走现有老路。

### 要补的 RS 规范（关键缺口）

RS L07 当前只到资产级（增量识别方式），缺**规则级/表级的驱动表+增量条件**。需要规范：
- 哪张表是增量驱动表
- 该表的增量识别方式（水位线字段 / 分区字段）
- 增量条件表达式
- 是否多驱动表（各自的增量范围）

---

## 十、待决（落地前还需定的）

- [ ] RS L07 的驱动表/增量条件规范怎么补（改 RS 模板 + rs-input-format + preprocess 解析）
- [ ] step_type / target_role / produces_for 的字段定义进 ts-template
- [ ] coder 怎么按 step_type 产不同 SQL（extract 产增量取数、merge 产 MERGE 语句）
- [ ] UT 怎么按 produces_for 依赖编排执行顺序（现有 schedule_groups 能否承载）
- [ ] designer.md / design-guide 怎么引导 designer 做增量设计（识别驱动表→拆步骤→声明依赖）

---

*本文档随讨论持续更新。第十节定完，转成正式设计方案落地。*
