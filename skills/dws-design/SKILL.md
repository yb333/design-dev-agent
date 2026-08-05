---
name: dws-design
description: >-
  DWS ETL 设计方法论。被 dws-designer agent 加载。
  指导 designer 如何从 rs_input.json 产出设计决策(design_decisions.yaml),
  再由 assemble_ts.py 组装成 TS 制品包(ts.json + ts.md)。
---

## ⚠️ 文件路径规则（必须遵守）

本 skill 的所有文件（references/ 下的模板、规范、脚本）都在 **skill 安装目录** 下，不在你的工作目录下。

### 怎么拿到 skill 安装目录的真实路径

加载 skill 后，opencode 会注入 skill 的 `location`（SKILL.md 的绝对路径）和 `<skill_files>` 文件列表。**用这些注入的路径**找 references 文件——location 的同级目录就是 references/。

### 读取 references 文件

用注入的 location 路径拼 references，例如：
- `{location所在目录}/references/design-decisions-template.yaml`
- `{location所在目录}/references/design-guide.md`

**绝对不要**按当前工作目录或 `~` 去拼路径——跨平台会出错。

---

# DWS ETL 设计 Skill

> 本 skill 被 **dws-designer** agent 加载，提供设计方法论。
> TS 制品包的 ts.json 结构权威定义见 `references/ts-template.json`（字段含义见文件内注释）。

---

## 1. 设计的核心任务

把需求（rs_input.json）转化为技术规格（TS），本质是：

> **把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑。**

规则是核心实体（一条 INSERT = 产出一个表）。场景是规则的属性。

**关键：designer 只产设计判断（design_decisions.yaml），不直接写 ts.json。**
字段类型/来源/注释等确定性数据由 `assemble_ts.py` 脚本从 rs_input.json 自动搬移。
这避免了 AI 手写大 JSON 的格式错误和上下文爆炸。

---

## 2. 设计流程（designer 的思考顺序）

### 步骤 1：理解需求
- 读 rs_input.json 的 meta（目标表 F+I、粒度、调度框架）
- 读 source_tables（源表关联关系）
- 读 field_mappings（字段映射 + 转换规则）—— 注意每个字段的 transform_rule（直接复制/数据加工/赋值/序列）

### 步骤 2：场景识别
- 同一业务实质的数据，来自不同来源、需不同加工逻辑 → 分场景
- 场景的本质：同一目标表的多来源并行加工
- 场景是规则的属性，不是独立结构层

### 步骤 3：规则拆分
- 把整体加工拆成多个规则
- 一个规则 = 一条 INSERT = 产出一个表（中间表 / 目标F表 / 视图I表）
- 每个规则在 design_decisions 的 `field_targets` 里列出它管哪些目标字段（target_column 名）

### 步骤 4：字段分配（关键）
- **每个 target_column 必须归属且仅归属一个规则**
- design_decisions 所有规则 field_targets 的并集 = rs_input 的所有 target_column
- 脚本会校验完整性，漏字段或重复分配会报错

### 步骤 5：设计思路与分段决策
详见 `references/design-guide.md` §4。核心：
- **design_approach**：写清楚整体设计策略（自然语言），讲清楚为什么这样拆、加工思路是什么。自然引用指标但不只列数字。
- 分段决策指标（JOIN 数/聚合字段数/粒度变化等）见 design-guide §4.1
- 分段结论 + 中间表决策（CTE 内联 vs 物理中间表）

### 步骤 6：字段加工逻辑
- **field_logics 只写加工类字段**（数据加工/赋值/序列）的 design_logic
- **直取字段（直接复制）不写**——脚本自动填 "直取 {alias}.{column}"
- design_logic = 自然语言口径（不含 SQL 表达式）

### 步骤 7：关联安全分析
- 每个被关联表：JOIN 键在限定条件下是否唯一
- 不唯一 → 对齐策略（GROUP BY 收敛 / 取最新有效行 / 等）

### 步骤 8：调度设计
详见 `references/design-guide.md` §5 调度设计。核心：

**调度类型**（从 RS L07 推导）：
- RS 的"调度频率"→ `schedule_type`：日调度→daily，小时/分钟级→hourly/realtime
- RS 的"增量识别方式"→ 判断是否增量场景

**增量设计**（如果增量）：
- `incremental.key`：增量识别字段（如 update_time / dt）
- `incremental.filter`：增量过滤条件（用起止双参数 BIZ_DATE_START / BIZ_DATE_END）
- `incremental.init_filter`：初始化过滤条件（全量用 `1=1`，或限定范围）
- `incremental.init_time_range`：初始化时间范围（RS L07）
- `incremental.init_strategy`：初始化策略

**依赖类型**（每个上游依赖选 dep_type）：
| 类型 | 含义 | 用在哪 |
|------|------|--------|
| 宽依赖（默认） | 当天或计划时间前后 N 小时内完成过 | 大部分场景 |
| 同周期依赖 | 同频同时，跑完才轮到我 | 同频任务 |
| 时间点依赖 | 等到指定时间点执行完成 | 精确控制 |
| 上周期依赖 | 匹配被依赖的上一个计划时间 | T-1 场景 |
| 虚拟依赖 | 依赖源端实时任务，查数据库判断状态 | 源端非周期任务 |

- `cron`：designer 填标准 cron 表达式
- I 视图和 DQ 的调度由脚本自动补，不需要填

### 步骤 9：产出 design_decisions.yaml + 调脚本组装
- 写 `design_decisions.yaml`（骨架见 `references/design-decisions-template.yaml`）
- 调 `assemble_ts.py` 组装出 ts.json + ts.md
- 脚本校验失败 → 修正 design_decisions 重跑

---

## 3. 中间表设计（螺旋式）

中间表设计是螺旋的——先骨架后回填：
1. **先骨架**：复杂度评估后决定建几个中间表，定表名/粒度/用途
2. **字段逻辑**：确定每个字段加工逻辑时，识别哪些字段落在中间表
3. **回填字段**：从字段分配回填出每个中间表的完整字段清单（在 field_targets 里列出）

中间表的字段绝大多数与目标表字段同名同类型（透传/聚合），极少量 designer 自建字段。
中间表统一加审计字段（脚本自动处理）。

---

## 4. 数据流图

- 节点 = 规则（产出表）
- 场景通过节点属性标记
- 多场景并行通过 schedule_groups 表达
- 在 design_decisions 的 data_flow 里定义 dependencies + schedule_groups

---

## 5. 参考文档

| 文档 | 内容 |
|------|------|
| `references/design-decisions-template.yaml` | **design_decisions 产出骨架**（你的产出模板，含填写规则注释） |
| `references/design-guide.md` | 命名规范 + 物理设计决策（分布键/分区）+ 字段分组原则 + 分段决策 |
| `references/rs-input-format.md` | RS 输入格式（理解输入） |
| `references/ts-template.json` | TS 制品包 ts.json 结构定义（字段含义见内注释，组装目标） |
| `references/ts-template.md` | ts.md 渲染骨架（7章结构） |

---

## 6. 产出检查清单

写好 design_decisions.yaml 后自检，再调脚本：

- [ ] rules 里每个规则有 rule_code / rule_name / field_targets
- [ ] field_targets 覆盖 rs_input 的所有 target_column（不漏不重）
- [ ] 如果 mapping 提供了审计字段（备注标"审计字段"），field_targets 要包含它们
- [ ] 审计字段不用写 field_logics（assemble 自动处理：来源有逻辑用来源的，没有补标准值）
- [ ] field_logics 只写加工类业务字段，直取字段不写
- [ ] design_logic 是自然语言口径，不含 SQL
- [ ] 场景是规则的 scenario 属性
- [ ] complexity_analysis 填了分段决策
- [ ] distribution_key 选了高基数 JOIN 字段（参考 design-guide.md §2.1）
- [ ] 调 assemble_ts.py 成功产出 ts.json + ts.md（无校验错误）
