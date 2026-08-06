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

## 七、待补充（请你补充想法）

- [ ] 你看到的"多源增量→临时表→MERGE"案例，有没有更具体的细节（几张源表、MERGE 的 key、增量范围怎么定）
- [ ] 增量场景在你实际业务里占比多少？是大部分资产要增量，还是少数？
- [ ] 临时表的命名/生命周期有规范吗（tmp_xxx 命名、是否每次重建）
- [ ] 方向 A/B/C 你倾向哪个，或者有第四种想法

---

*本文档随讨论持续更新。定方向后转成正式设计方案，再落地改代码。*
