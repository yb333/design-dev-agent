---
name: dws-design
description: >-
  DWS ETL 设计方法论。被 dws-designer agent 加载。
  指导 designer 如何从 rs_input.json 产出设计决策(design_decisions.yaml),
  再由 assemble_ts.py 组装成 TS 制品包(ts.json + ts.md)。
---

## ⚠️ 文件路径规则（必须遵守）

本 skill 的所有文件（scripts/ 下的脚本、assets/ 下的模板、references/ 下的指导知识）都在 **skill 安装目录** 下，不在你的工作目录下。

### 怎么拿到 skill 安装目录的真实路径

加载 skill 后，opencode 会注入 skill 的 `location`（SKILL.md 的绝对路径）和 `<skill_files>` 文件列表。**用这些注入的路径**找文件——location 的同级目录下分三类：
- `scripts/`：脚本（.py）
- `assets/`：模板（骨架、example 配置，带 template/example 后缀）
- `references/`：指导知识（规范、方法论、格式说明等文档）

### 读取文件

用注入的 location 路径拼目录，例如：
- `{location所在目录}/assets/design-decisions-template.yaml`（模板骨架）
- `{location所在目录}/references/design-guide.md`（规范文档）
- `{location所在目录}/scripts/assemble_ts.py`（脚本）

**绝对不要**按当前工作目录或 `~` 去拼路径——跨平台会出错。

---

# DWS ETL 设计 Skill

> 本 skill 被 **dws-designer** agent 加载，提供设计方法论。
> TS 制品包的 ts.json 结构权威定义见 `assets/ts-template.json`（字段含义见文件内注释）。

---

## 1. 设计的核心任务

把需求（rs_input.json）转化为技术规格（TS），本质是：

> **把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑。**

规则是核心实体（一条 INSERT = 产出一个表）。场景是规则的属性。

**关键：designer 只产设计判断（design_decisions.yaml），不直接写 ts.json。**
字段类型/来源/注释等确定性数据由 `assemble_ts.py` 脚本从 rs_input.json 自动搬移。
这避免了 AI 手写大 JSON 的格式错误和上下文爆炸。

---

## 2. 设计流程：五层决策骨架（★ 思考主线）

> 设计是从目标表**倒推**的过程。每一层有明确的"想清楚什么 + 产出什么 + 闭合条件"。
> 前一层没闭合就不该进下一层——闭合条件由 assemble_ts 校验兜底，没过会被 fail-loud 拦回。

先读 `rs_input_view.json` 的 compact 视图建立认知（不是 rs_input.json 全文）：
- `tables`：源表清单（哪些表、规模、关联）→ 理解全貌、判断数据源缺口
- `direct`：直取/赋值字段按源表分块 → 批量搬运字段扫一眼过
- `processed`：加工字段逐个平铺（含完整多步骤口径/多表来源合并）→ 逐个拆解加工链
- `incremental_tables`（如有）：增量驱动表清单
- 需要某字段精确细节（如完整 source_type）时再查 rs_input.json 的 field_mappings

### 第0层 锚点（强制闭合）— 产出表粒度 + 业务主键

**想清楚**：这张表"一行 = 什么业务实体"？业务主键（business_key）在产出粒度下能不能唯一框定一行？
- BA 在 mapping/RS 里标的主键是**业务视角**，designer 必须确认它在产出表的**物理粒度**下唯一
- 粒度变化（头行整合、聚合收敛）会让原主键发散 → 必须补字段让主键唯一
- 这层错，后面全错（主键发散 → UT 数据质量失败最高频根因）

**产出**：`grain.input/output`、`business_key`、`business_key_design`（input_key/adjusted/reason）
**闭合条件**（assemble_ts 硬校验）：grain 非空 + business_key 非空 + business_key_design 论证完整 + business_key 字段在目标表存在

### 第1层 字段血缘（含场景横切）— 逐字段定来源身份

**想清楚**：每个目标字段的值从哪来、怎么来？来源身份三种：
- **直取**：值直接从某源表字段复制 → 归该源表所在的规则
- **加工**：值由多字段加工算出 → 归执行该加工的规则
- **赋值**：值是固定值/序列 → 归目标表对应的规则

**场景是这层的横切属性**（不单列一层）：同一目标表的数据来自不同来源、需不同加工逻辑 → 多场景。判断依据是"来源不同/加工逻辑不同"，天然在分析字段血缘时识别。场景是规则的 `scenario` 属性。

**产出**：每个规则 `field_targets`（它管哪些目标字段）
**闭合条件**：每个 target_column 归属且仅归属一个规则；目标表规则 field_targets 并集 = rs_input 所有字段（中间表字段不算）

### 第2层 加工路径 — 组织成路网

**想清楚**：把字段血缘组织成加工路径。路径的汇合点 = 中间表（CTE 内联或物化物理表）。
- **物化 vs CTE 决策**：满足任一条件就物化——多次引用 / 估算偏差>10x / 数据量大（亿级倾向物化）/ 需要检查点 / 跨步骤传递。否则用 CTE 内联。
  → 完整决策标准见 `references/complexity-playbook.md`
- **中间表产出模式**：单一规则一次性产出（`build_mode: transform`，默认）/ 多规则累积共建（`build_mode: accumulate`，去重或 union）。
  → 累积共建的排重策略见 `references/incremental-playbook.md` §三/§四
- **数据量因子**：RS data_exploration 或 explore.py 估档位（万/百万/亿），拿不到标"未知"，只影响物化决策，不阻断

**产出**：每个规则 `step_type` + `target_role` + 依赖声明（`produces_for` / `reads`）
**闭合条件**（assemble_ts 校验）：step_type/target_role 合法且不矛盾；中间表有消费者；依赖声明闭合（无悬空、无循环、顺序合法）

### 第3层 时间属性（含场景横切）— 每条路径单独定性增量/全量

**想清楚**：每条数据路径是增量还是全量？增量的话驱动表是谁、增量字段是什么？
- **增量是"路径属性"，不是"表属性"**——多张驱动表 = 多条独立路径，各自有增量范围
- **逐表对账**（防臆想）：RS 声明了 N 张增量驱动表，就必须有对应覆盖的 extract 步骤。最容易出错的是臆想"主从关系只做主表"——每张驱动表漏做都会丢增量数据
- 场景在这层也是横切：不同来源路径可能增量/全量不同

→ 增量设计的完整决策（数据流/load_mode/初始化/累积共建排重）见 `references/incremental-playbook.md`

**产出**：增量规则的 `incremental` 段（key/filter/init_*）；merge 规则的 `load_mode`
**闭合条件**（assemble_ts 硬校验）：驱动表数 ≤ extract 规则数；extract 的 incremental 填全；每张驱动表字段被覆盖（默认拦，合并场景可填豁免 reason）

### 第4层 工程保障 — 分布键 + 关联安全 + 调度

**想清楚**：
- **分布键**：按业务主键 / 关联使用频率（减少重分布）/ 离散程度选，与数据量无关。多表 JOIN 时各表分布键必须一致。
  → 详见 `references/design-guide.md` §1.1
- **关联安全**：每个被关联表，JOIN 键在限定条件下是否唯一。不唯一 → 对齐策略（GROUP BY 收敛 / 取最新有效行）。
  不确定时调 explore.py 验证（只读单表，不 JOIN，不会发散）：
  ```
  python {location所在目录}/scripts/explore.py --ts {deliver}/ts.json \
      --check-join-key --schema {sch} --table {tbl} --key {col} --where "{join_filter}"
  ```
  看结果填 `join_key_unique`（✅ 唯一 / ❌ 不唯一）。连不上库会静默跳过，不阻断设计。
- **调度**：schedule_type（从 RS 调度频率推导）、cron（Quartz 6 段标准表达式）、依赖类型（默认宽依赖）
  → 依赖类型选择见 `references/design-guide.md` §二

**产出**：`tables.{表}.distribution_key`、`join_safety`、`schedule`
**闭合条件**（assemble_ts 校验）：schedule_type 合法；cron 格式合法；distribute_type 合法；distribution_key 字段在所属表存在

### 字段加工逻辑（贯穿第1-2层）

- **field_logics 只写加工类字段**（数据加工/赋值/序列）的 design_logic（自然语言口径，不含 SQL）
- **直取字段不写**——脚本自动填 "直取 {alias}.{column}"
- 加工字段没写 design_logic 会被硬校验拦住（不允许占位继续跑）

### 产出 + 组装

- 写 `design_decisions.yaml`（骨架见 `assets/design-decisions-template.yaml`）
- 调 `assemble_ts.py` 组装出 ts.json + ts.md
- 校验失败 → 看报错的 `[第X层]` 标识定位到对应 playbook 修正后重跑

### 路由段：什么时候读哪个 playbook

| 触发条件 | 读哪个 |
|---------|--------|
| RS 标了增量（L07 增量识别方式 ≠ "不涉及"）| `references/incremental-playbook.md` |
| 第2层评估命中复杂度阈值 / 数据量大 / 要拆中间表 | `references/complexity-playbook.md` |
| 累积共建场景（多规则写同一中间表）| `references/incremental-playbook.md` §三/§四 |
| 分布键/分区/依赖类型 | `references/design-guide.md`（每次都薄，直接读）|

> 简单全量单表资产：五层很快走完，第2层不拆中间表（走 full 单规则），第3层全量，只读 design-guide.md 就够。

---

## 3. 数据流图

- 节点 = 规则（产出表）
- 场景通过节点属性标记
- 多场景并行通过 schedule_groups 表达
- 在 design_decisions 的 data_flow 里定义 dependencies + schedule_groups

---

## 4. 参考文档

| 文档 | 内容 | 何时读 |
|------|------|--------|
| `assets/design-decisions-template.yaml` | **design_decisions 产出骨架**（含填写规则注释） | 写产出时 |
| `references/design-guide.md` | 物理设计决策（分布键/分区）+ 依赖类型 | 每次都读（薄） |
| `references/incremental-playbook.md` | 增量设计全集（数据流/累积共建/排重/初始化） | RS 标了增量时 |
| `references/complexity-playbook.md` | 复杂度评估 + CTE/物化决策 + step_type 决策树 | 拆中间表/复杂场景时 |
| `references/rs-input-format.md` | RS 输入格式（理解输入） | 需要时查 |
| `assets/ts-template.json` | TS 制品包 ts.json 结构定义 | 组装目标参照 |
| `assets/ts-template.md` | ts.md 渲染骨架 | 渲染参照 |

---

## 6. 产出检查清单（按五层）

写好 design_decisions.yaml 后自检，再调脚本（校验项对应 assemble_ts 的分层校验）：

**第0层 锚点**
- [ ] `grain.input/output` 非空（一行 = 什么业务实体）
- [ ] `business_key` 非空，且字段都在目标表存在
- [ ] `business_key_design` 论证完整（input_key / adjusted / reason；adjusted=false 时 reason 写"沿用输入主键，产出粒度未变"）

**第1层 字段血缘**
- [ ] rules 里每个规则有 rule_code / rule_name / field_targets
- [ ] 每个 target_column 归属且仅归属一个规则（目标表规则并集覆盖 rs_input 全字段）
- [ ] field_logics 只写加工类业务字段（直取字段不写，脚本自动填）
- [ ] design_logic 是自然语言口径，不含 SQL
- [ ] 如果 mapping 提供了审计字段（备注标"审计字段"），field_targets 要包含它们；审计字段不用写 field_logics（assemble 自动处理）

**第2层 加工路径**
- [ ] 每个规则有 step_type（full / aggregate / incremental_extract / merge，见 complexity-playbook §四）
- [ ] target_role 与 step_type 不矛盾（见 complexity-playbook）
- [ ] 多步骤时声明依赖：中间表填 produces_for，装配/merge 填 reads
- [ ] 累积共建表标了 `build_mode: accumulate`，排重场景填了 dedup_strategy

**第3层 时间属性**
- [ ] 增量场景：每张驱动表都有对应的 extract 步骤覆盖（见 incremental-playbook）
- [ ] extract 规则的 incremental.key/filter/init_filter 填全

**第4层 工程保障**
- [ ] distribution_key 选了高基数 JOIN 字段（参考 design-guide.md §1.1）
- [ ] schedule.schedule_type 合法（daily/hourly/realtime）
- [ ] schedule.cron 是 Quartz 6 段表达式
- [ ] 复杂度/分段决策写进 complexity_analysis.design_approach（进 ts 文档）

**组装**
- [ ] 调 assemble_ts.py 成功产出 ts.json + ts.md（无校验错误；失败看报错的 `[第X层]` 定位）
