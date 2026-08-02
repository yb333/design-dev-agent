---
status: active
last_reviewed: 2026-07-29
---

# 设计开发 Agent · 架构文档

> **本文是设计开发段的唯一架构文档。** 所有架构认知在此一处维护。
> 历史推理见 `design-dev-discussion-points.md`（15 论点，部分已被本文演进）。
> 格式契约见 `docs/specs/`（ts-format / rs-input-format）。

---

## 一、定位与边界

### 1.1 这是什么

**设计开发段**——数据交付全流程（DDLC）的中游主力段：

```
需求 → [RS生成] → [设计开发] → 测试 → 运维
                    ↑本项目
```

一个 agent 系统连续完成「设计 → 编码 → UT」，中间在粗设计后有**闸口①**让人确认方向。

> **关于闸口与代码 review**：
> - agent 流程内**只有一个闸口——闸口①**（TS 设计后，人审方向）。这是流程内阻塞点，agent 暂停等人确认。
> - **代码正确性靠螺旋回路保证**（跑通 + 机械检查），不需要独立审查闸口。
> - **代码 review（committer 审查合入）是段外 gate**，不是段内闸口：agent 跑完螺旋回路、代码稳定即段内完成；产出代码上传代码仓后由 committer review 合入。这是团队代码质量治理，不阻塞 agent 流程，agent 不负责。

```
设计开发段（agent 流程内）：预处理→designer产TS→⏸闸口①→coder按规则螺旋→代码稳定=段内完成
                                                                      ↓ 产出代码
                                                          代码仓 committer review（段外 gate）
                                                                      ↓ 合入
                                                                   交付下游
```

### 1.2 三条红线

- **语义判断不自主**：数据合理性、模式选择、字段语义 → 给材料，人定
- **推到生产不自主**：写生产库、推规则上线 → 生成制品，人推
- **重写不自主**：优化推倒重来 → 只精确修改，想重写走新建

### 1.3 不属于本项目

- 代码理解 Agent（analyzer）：独立建仓，优化场景调用其产出
- RS生成 / 测试 / 运维段：其他 agent 负责，靠 spec 文件交接

---

## 二、环境事实（地基）

### 2.1 两个环境，单向数据流

```
┌──── 外网（本机/本仓）────┐      ┌──── 内网（生产）────┐
│ zcode + GLM-5.2         │ 外网  │ codeagent(opencode套壳)│
│ opencode 原生能力完整   │ 内容  │ + minimax-2.7/glm-5.0 │
│ postgresql-executor MCP │ 可进  │ + 对接平台skill(自研) │
│ 能开发、能近似验证      │ ───→  │ + 也可用zcode+5.2调试 │
└─────────────────────────┘      └───────────────────────┘
          ▲                                 │
          └──── 内网内容拿不出来（单向门）──┘
```

### 2.2 关键事实

| 事实 | 影响 |
|---|---|
| codeagent 是 opencode 套壳，原生能力完整 | 架构可依赖 opencode 原生（agents/permission/Task/question） |
| 内网模型 minimax-2.7/glm-5.0；本机 glm-5.2；内网也可用5.2 | 主体逻辑用5.2开发验证；minimax/5.0兼容性独立验证 |
| 对接平台能力是内网自研 skill | 本仓只产出制品+约定接口，运行验证在内网 |
| 去掉 oh-my-opencode 插件 | 损失通用agent(sisyphus等)，用 agents/*.md 自定义领域agent替代 |

### 2.3 工作模式：近似验证 + 差异清单

- **本仓**：产出 agent/skill/command/schema/模板 + 用5.2近似验证主体逻辑
- **差异清单**（本机验证不了，内网必须验证）：① 对接平台运行 ② 模型兼容(minimax/5.0)

---

## 三、整体架构

### 3.1 六层架构（纵向）

```
L5 交互层    桌面应用（客户端仓负责）
L4 Pipeline  端到端编排（本项目是其中一段，靠spec交接）
L3 Stage     段（command编排 + spec契约 + 闸口）★ 本项目
L2 执行单元  agent / skill / 脚本 / MCP
L1 协议层    spec schema + 校验（⭐地基，横跨所有区）
L0 宿主层    codeagent/opencode（黑盒依赖）
```

### 3.2 四区组件结构（横向 · 协作边界）

```
┌─ ① 主体能力（TS+代码）─────────────────────────┐
│  吃RS输入 → 产TS制品包 + 可跑的SQL/DDL          │
│  designer / coder（agent）+ 预处理/执行（脚本） │
└─────────────────────────────────────────────────┘
              ↓ 契约：ts.json + ts.md + SQL/DDL
┌─ ② 制品能力（适配器模式）──────────────────────┐
│  核心逻辑（①）产出平台无关的中间表达            │
│  制品层是适配器：平台如何变化，核心内容不受影响  │
│  exporter 产中间表达 → 平台适配器部署到各平台    │
└─────────────────────────────────────────────────┘

┌─ ③ 评测体系（离线）────────────────────────────┐
│  离线评测①②产出质量（不连环境，对比golden/查规范）│
│  eval-suite（独立工程）                          │
└─────────────────────────────────────────────────┘

┌─ 编排层（横跨①②）──────────────────────────────┐
│  orchestrator（主agent）+ designer/coder（子agent）│
│  + command（任务流剧本）                          │
└─────────────────────────────────────────────────┘
```

**块间靠契约交接**（spec文档定义格式），不耦合内部实现。

> **② 制品能力的适配器模式**：核心逻辑（①主体能力）产出**平台无关的中间表达**（DDL/SQL + 制品格式），制品层是适配器，负责把中间表达部署到各平台（术加/LTS/DQ）。**平台如何变化，对核心内容没有影响**——换平台只改适配器，不改核心。

### 3.3 三横切维度

| 维度 | 机制 |
|---|---|
| 🛡️ **安全** | ask(question闸口) / allow(whitelist) / **deny(permission硬拦截，待补)** |
| 🔌 **对接** | 读用MCP/脚本（agent自主），写生产靠人推（红线） |
| 📊 **评估** | 代码稳定(agent判，螺旋回路) vs 数据准确(人判，不可自动) |

---

## 四、螺旋回路与现实约束

### 4.1 理想形态 vs 当前绕过

> **理想形态**：螺旋回路的"执行"接点，应该是把 DML/ETL 语句丢到**平台**里，由平台执行并回传结果。平台是执行者，agent 是提交者。
>
> **当前绕过**：平台暂无机机接口，不得已**绕过平台直连数据库**执行 SQL——这是过渡手段，不是目标。直连库能验证 SQL 本身的正确性，但验证不了平台调度的正确性。

### 4.2 螺旋回路的三段（当前现实）

```
段1：单规则数据库验证 ─── ✅ 能自动闭环
  DDL建表 + 单条ETL跑 + 捞日志 + 改 → 闭环

段2：多规则顺序执行 ─── ❌ 当前人工（过渡）
  规则间有依赖，上一规则跑几分钟十几分钟，无自动调度依赖

段3：平台验证 ─── ❌ 当前人工（过渡）
  术加浏览器模拟导入（需人启动、拿不到反馈）
  LTS静态检查能做但起调验证做不到
```

### 4.3 这是过渡状态，非长期前提

- **术加平台2.0**（重做中）将支持 MCP 能力，未来段3可无缝接入
- 段2是技术问题（加调度依赖可解）
- **架构保留完整螺旋回路的扩展空间，不按残缺写死**

### 4.4 当前能力边界（影响 agent 结束点）

| 能力 | 当前状态 | 谁 |
|---|---|---|
| 单规则跑通+机械检查(主键不发散等) | ✅ 执行脚本可做 | coder调脚本 |
| 多规则按依赖顺序跑通 | ❌ 人工 | 人 |
| 术加平台部署运行验证 | ❌ 人工 | 人 |
| LTS起调验证 | ❌ 人工 | 人 |

**agent 的"代码稳定"结束点 = 段1通过 + 段2/3标注"未验证"**。

---

## 五、Agent / Skill / Command 架构

### 5.1 核心概念：项目是"agent 系统"

"设计开发 Agent"不是一个 agent 实例，是一个系统：
```
= dws-orchestrator（主agent，领域引擎）
  + dws-designer / dws-coder（子agent，能力零件）
  + 脚本工具（预处理/执行/导出）
  + command（任务流剧本）
```

### 5.2 组件清单

> **编排定位**：设计开发段不定义自己的 primary agent。编排逻辑（各种 loop / 流程控制 / 质量保障回路）沉淀在 **command** 里，由任意 primary agent（项目主 agent 或 opencode 内置 build）执行。设计开发段提供的是：子 agent + skill + 脚本 + command。

| 组件 | 类型 | 职责 |
|------|------|------|
| **dws-designer** | subagent | rs_input.json → TS制品包（ts.json+ts.md） |
| **dws-coder** | subagent | TS规则 → SQL/DDL（含调执行脚本+自改报错） |
| 输入预处理 | 脚本 | mapping+RS → rs_input.json + 预检 |
| 执行脚本 | 脚本 | 连库跑SQL+机械检查（不占上下文，能等十几分钟） |
| 导出脚本 | 脚本 | SQL+TS → 制品中间表达 |
| **/new-pipe** | **command** | **编排逻辑的核心载体**（预处理→designer→闸口→coder螺旋→导出） |
| /optimize | command | 优化任务流（未来） |
| dws-design-skill | skill | designer加载：设计方法论+模板 |
| dws-coding-skill | skill | coder加载：编码规范+模板 |

**核心 subagent 只有2个（designer/coder）**。理由：只有"上下文隔离有收益+需AI理解"的才用agent；tester降级为脚本（UT是机械检查），exporter/预处理是确定性脚本。

> **编排不依赖特定 agent**：command 的机制是"注入 primary agent 的指令模板"。项目主 agent（或内置 build）触发 /new-pipe 后，按 command 正文执行编排——调子 agent、管闸口、调脚本。编排逻辑在 command 里，不在某个 agent 的 prompt 里。这样：① 不和项目主 agent 冲突（它是执行者不是编排者）；② 没有项目主 agent 时用内置 build 也能跑。

### 5.3 为什么 designer 和 coder 必须合并成"一个段"（不分成两个独立段）

> **质疑**：既然 designer 和 coder 是两个独立子 agent，靠 ts.json 交接，那"设计开发一体"不就是自相矛盾吗？为什么不干脆分成"设计段"+"开发段"两个独立段？

**回答**：designer 和 coder 是**一个工作单元内部的实现分工**，不是两个独立段。"一体"指的不是"一个 agent 实例"，而是"一个不向外部交接的工作单元"。必须合并的硬理由：

| # | 理由 | 说明 |
|---|------|------|
| 1 | **返工回路必须闭环** | 编码发现设计问题要回改 TS，段内闭环比跨段交接快得多。返工回路见 §5.4 |
| 2 | **闸口①调整必须即时** | 人确认方向时经常要调设计，段内即时调整；跨段要退回重做 |
| 3 | **TS 是活契约不是交付物** | TS 和代码一起演进（coder 发现问题回改 TS），必须同一主体持有，不能两段争抢所有权 |
| 4 | **认知连贯性** | 数据开发的设计（想字段怎么算）和编码（写SQL）认知上连续，跨段会断 |

> 对比：分成两个独立段 = 两个组织签合同（跨段交接）；合并成一个段 = 一个部门内两个岗位协作（段内分工）。论点1反对的是前者。

### 5.4 质量保障体系（含段内重做回路）

> **核心问题**：AI 产出本质不稳定（随机性 + 设计判断错 + 编码不合规）。架构必须显性化"怎么保证产出对"。
>
> **策略**：每个关键产出后有检查点，不通过回最近的产出者重做（≤3轮，超则闸口问人）。越靠后的检查点确定性越强（脚本/人判），越靠前越依赖 AI。

**段内检查点 + 重做回路**：

```
预处理 → [预检] ─不通过→ 拦住问人（输入问题）
   ↓ 通过
designer 产 TS → [TS校验] ─不通过→ 回 designer 重做
   ↓ 通过
⏸ 闸口①（人确认方向/口径） ─不通过→ 回 designer 调整
   ↓ 通过
coder 产 SQL → [静态检查·规范] ─不通过→ 回 coder 重写
   ↓ 通过
执行 SQL → [机械检查·跑通+主键+行数] ─不通过→ 回 coder 改（螺旋）
   ↓ 通过
跨规则 → [一致性检查] ─不通过→ 回相关规则重做
   ↓ 通过
导出制品 → 段内完成
```

**各检查点详情**：

| 检查点 | 查什么 | 怎么查（确定性） | 不通过回谁 |
|--------|--------|-----------------|-----------|
| 预检 | 输入齐全/格式对/字段覆盖 | 脚本（确定性） | 人（拦住补输入） |
| TS 校验 | 结构完整/字段覆盖RS/血缘一致 | **脚本 + AI 结合**（结构脚本查，合理性AI查） | designer 重做 |
| 闸口① | 方向/口径对 | 人（红线①） | designer 调整 |
| 静态检查 | SQL 规范合规（不能SELECT*/NULL处理/审计字段） | 脚本（确定性规则） | coder 重写 |
| 机械检查 | 跑通+主键不发散+行数合理 | 执行脚本（确定性） | coder 改（螺旋） |
| 一致性检查 | 跨规则字段/血缘/审计完整 | 脚本 + AI 结合 | 相关规则重做 |

**重做回路要点**：
- 不通过**回最近的产出者**（不回退到最前面）——静态检查不通过回 coder，不回 designer
- 每个检查点 **≤ 3 轮**，超过闸口问人
- 编码中发现 TS 明显问题：简单回报 orchestrator，由 orchestrator 决定是否回 designer（**不设复杂分类机制——因编码中返工不多，真实大量返工在测试后跨段**）

**段外质量（不阻塞流程，是改进闭环）**：
- **eval-suite**（离线）：对比 golden / 查规范，发现系统性问题反馈改进 skill/规范
- **committer review**：代码合入 gate（段外）
- **SIT 测试**（跨段）：跑数据验证准确性，发现的真实大量返工走优化场景/跨段反馈

> **eval-suite 与段内检查的关系**：段内检查是流程内的质量 gate（不通过不能往下走）；eval-suite 是事后的质量评测（发现系统性偏差，持续改进）。两者不重复——段内查"这次产出对不对"，eval-suite 查"这个 agent 整体产出稳不稳定"。

### 5.6 编码段架构定稿（2026-08-02 讨论确定）

> 编码段比设计段复杂得多（多规则/螺旋回路/执行依赖），以下架构经多轮讨论定稿。

**一、coder 产出结构**：
- **DDL**（建表/建视图）：coder 从 ts.json 字段定义生成。**不定义物理 PRIMARY KEY/FOREIGN KEY**（DWS 列存限制）
- **SELECT**（加工逻辑）：coder 从 design_logic 翻译。**核心产出**
- **INSERT**：不由 coder 拼。由脚本按平台固定规则包装（SELECT + 字段列表 + 审计字段 + 参数替换），交制品包导入环节
- **UT 检查 SQL**：不由 coder/AI 生成。由脚本从 ts.json 结构信息按模板自动生成

> **关键决策：现实是开发人员写 SELECT，平台拼 INSERT**。coder 产 SELECT+DDL，INSERT 的拼装是确定性的（平台规则固定已知），交脚本。

**二、验证分层**：
- **静态对比**（生成时，不连库）：SELECT/DDL 和 ts.json 结构是否一致（表/字段/类型/JOIN）。coder 内循环，限3轮。
- **连库执行 + UT**（全部生成后）：脚本跑 DDL+INSERT + 6项 UT 检查。command 编排。

**三、UT 检查项**（全脚本化，不需要 AI）：
1. DDL 执行通过
2. INSERT 执行通过
3. 记录数合理（>0，未暴增）
4. **业务主键唯一**（注意：从 ts.json business_key 取，不是物理 PRIMARY KEY，DDL 不定义约束）
5. 必填字段非空（审计字段/业务主键）
6. 数据截断检查（目标字段类型长度 ≥ 源）

> **UT/SIT 边界**：UT = 脚本结构正确性（能跑通+不发散），SIT = 数据业务正确性（金额/口径/跨源比对，要预期值）。UT 挡低级错误，业务正确性留 SIT。

**四、流程编排（command）**：
```
阶段1 生成（逐规则，不连库）：Task(coder) → 产 SELECT+DDL → 静态对比 → 自闭环改
阶段2 执行验证（连库）：脚本跑 DDL+INSERT+UT → 报告
阶段3 执行回路（如有失败）：SQL错→回调coder / 环境/设计错→报告人
阶段4 闸口②：人确认 → 交付 SIT 或处理失败
```

**五、关键设计原则**：
- **生成和执行分离**：生成不连库（静态对比），执行在全部生成后统一做。避免权限/依赖卡住后续生成。
- **规则间依赖**：data_flow.schedule_groups 定义执行顺序。生成时 coder 不需要前序表存在（它依据 ts.json 写 SQL，不是依据数据库）。
- **业务主键 ≠ 分布键**：ts.json 要加 business_key 字段（显式业务主键），UT 用它查唯一性。distribution_key 是数据分布最优选，不一定等于业务主键。

**六、coder 职责定稿（2026-08-02 讨论确定）**：

> coder 的唯一产出是 **SELECT 语句**。DDL/INSERT包装/UT检查全脚本化，coder 不碰。

**coder 不碰的（全脚本化）**：
- **DDL**：assemble_ddl.py 从 ts.json 自动生成（表名/字段/类型/分布键/审计字段，全是 ts.json 里的确定性信息）
- **INSERT 包装**：run_ut.py 内部做（读 SELECT 文件 + ts.json 字段定义 + 审计字段模板 → 拼完整 INSERT → 执行）
- **UT 检查 SQL**：run_ut.py 自动生成（主键唯一/非空/行数/截断，从 ts.json 结构信息按模板生成）

**coder 的内部流程**：
```
1. 调 slice_ts.py 拿规则切片（不读整个 ts.json，防止大表上下文爆炸）
2. 读 dws-coding skill（规范+SELECT模板）
3. 写 SELECT 语句（从切片的 design_logic 翻译成 SQL）
4. 调 check_sql.py 静态对比（SELECT vs ts.json 切片）
   ├─ 不过 → 自己改 → 重对比（限3轮）
5. 落盘 SELECT 文件，回报完成
```

**编码段脚本清单**（都在 dws-coding skill 的 references）：

| 脚本 | 干什么 | 谁调 |
|------|--------|------|
| `slice_ts.py` | ts.json 按规则切片（输出单个规则的 YAML） | coder |
| `check_sql.py` | SELECT vs ts.json 切片静态对比 | coder |
| `assemble_ddl.py` | 从 ts.json 生成全部规则的 DDL | command（执行阶段） |
| `run_ut.py` | 包装INSERT + 执行DDL/INSERT + UT检查 + 报告 | command（执行阶段） |

**command 编排（带会话恢复）**：
```
阶段1 生成：按 schedule_groups 分层，逐规则 Task(coder) → coder 产 SELECT
           command 记住每个规则的 task_id（规则→会话映射）
阶段2 执行：assemble_ddl.py 生成DDL → run_ut.py 执行+UT → 报告
阶段3 执行回路：SQL错 → Task(coder, task_id=xxx, "带报错改") 恢复原会话
           重跑 run_ut.py → 限3轮
阶段4 闸口②：汇总报告，人确认
```

**七、优化场景架构预留（2026-08-02 讨论确定）**：

> 优化场景（改已有表/已有 ETL）采用**增量模式**而非全量重做。理由：全量重做会让没改的部分也产生 AI 波动性变化，导致 review 困难、产出不稳定。
> **当前阶段只做新建，但架构预留增量扩展点，不堵路。**

增量模式相比新建需要额外能力（当前不实现，但架构预留）：
1. **变更描述格式**：优化输入不是全量 mapping，而是"改什么"的增量描述
2. **现有结构作为上下文**：designer/coder 要看现有 ts.json / 现有 SELECT
3. **增量设计/编码**：只改变更部分，不重做全部
4. **ALTER DDL**：对比现有表结构生成 ALTER（加/删/改字段）
5. **变更安全性验证**：ALTER 类型变更不丢数据

架构预留点（新建实现时不堵死的扩展点）：

| 环节 | 预留点 | 新建时怎么做 | 增量时怎么扩展 |
|------|--------|------------|--------------|
| ts.json 结构 | field 可选 `_changed` 标记 | 不加（全量新建） | 标记变更字段 |
| preprocess | 输入格式 | 读全量 mapping | 额外读变更描述 merge |
| designer | agent body | 全量设计 | 接受现有 ts.json + 变更，只改部分 |
| assemble_ts | 组装模式 | 全量组装 | 读现有 ts.json + 增量决策合并 |
| assemble_ddl | 输出模式 | 全量 CREATE | 对比现有表结构生成 ALTER |
| coder | agent body | 全量写 SELECT | 接受现有 SELECT + 只改变更部分 |

**八、DQ 质量检查分工（2026-08-02 讨论确定）**：

> DQ 不是 UT 的子集，是独立的质量维度。两者形态不同（UT 检查结构正确性，DQ 检查数据质量），但执行方式统一（都跑 SELECT 看有没有违规行）。

**DQ 三层分工**：

| 层次 | 例子 | 谁生成 | 什么时候 |
|------|------|--------|---------|
| 标准 DQ（已归入 UT） | 主键唯一/必填非空/行数 | run_ut.py 脚本自动 | UT 阶段 |
| 模板化 DQ | 值域（del_flag 只能 Y/N）、枚举、唯一性 | run_ut.py 从 dq_rules 按模板生成 | UT 阶段 |
| 定制 DQ | 跨表一致性、复杂业务规则 | **coder 单独产**（DQ 检查 SELECT） | DQ 阶段（编码后可选） |

**DQ 设计意图来源**：RS 写 DQ 意图 → designer 细化进 ts.json 的 dq_rules（自然语言，不写SQL）。
**定制 DQ SQL**：command 额外调一个 coder（专门干 DQ），不和加工 coder 混。
**DQ 执行**：DQ SQL 和 UT SQL 执行方式统一（跑 SELECT 看违规行），但生成方式分层（模板/ coder 产）。

**九、数据库执行能力内化（2026-08-02 讨论确定）**：

> 现阶段整个 agent 项目是闭包自洽的。数据 MCP server（独立进程）是多余中间层。**内化成 Python 共享模块（dws_db.py），删掉 MCP server。**

**内化设计**：
- `dws_db.py`：数据库执行模块，放 dws-coding skill 的 references
- **接口与实现分离**：上层（run_ut.py 等）只依赖 `DBExecutor` 接口（execute/switch_source/test_connection）
- **现阶段实现**：PsycopgExecutor（psycopg2 直连）
- **未来扩展**：MCPExecutor（走术加平台 2.0 MCP）/ PlatformExecutor（走平台 API）——只换实现类，上层不改

**配置统一**：db-sources.json（多 schema 多账号映射），脚本和未来 agent 共用。install.py 提示用户配置。
**MCP server 处理**：删 mcp-servers/postgresql-executor/。核心逻辑（多数据源/SQL执行/安全限制）翻译进 dws_db.py。同步更新文档和测试引用。

**eval-suite 设计约束（2026-07-31 讨论确定）**：
1. **目的是找问题，不是打分**——评测是"探针"，核心价值是暴露 AI 产出和预期之间的偏差（哪里有问题、什么类型的问题），不是给一个总分排名。输出应是"问题清单"而非"分数报告"。
2. **内网完全隔离，结果只能拍照/手敲带出**——评测结果文件无法导出。因此结果输出必须极简可读（一张截图能装下），通过项折叠成计数，只展开问题项（带类型 + 上下文，让人不用回内网翻文件就能判断严重程度）。
3. **通过 opencode(codeagent) 跑**——评测在内网通过 opencode sidecar API 自动执行（发 prompt → 等完成 → 校验），runner 复用现有 eval-suite/runner.py 的 cmd_execute 框架。
4. **评测标准：结构约束为主，golden 对比为辅**——设计段 AI 自由产出（规则拆分/design_logic 写法），不能逐字对比 golden；结构约束（字段完整性/审计规范/格式正确）是硬指标必过，关键点 golden 对比看偏差幅度。
5. **分步骤 + 端到端两种评测**——端到端跑全流程看整体，分步骤（preprocess/designer/assemble 各自）定位具体环节问题。

### 5.5 三者关系

```
command（编排逻辑：怎么干——各种loop/流程/质量保障）
  ↓ 注入给
任意 primary agent（执行者：项目主agent 或 内置build）
  ↓ Task调用子agent（子agent加载各自skill）
dws-designer / dws-coder（能力零件：加载skill作知识）
  ↓ bash调用
脚本（preprocess/validate_ts/execute/export）
```

- **command** = 编排逻辑的核心载体（各种 loop / 流程控制 / 质量保障回路都写在这里）
- **primary agent** = 执行者（按 command 指令执行，不需要懂设计开发领域知识）
- **子agent** = 能力零件 → 加载各自skill作为知识
- **skill** = 知识包（需加载到上下文才用）→ 按知识归属划分，permission.skill隔离
- **格式文档** → read获取，不是skill
- **脚本** → bash调用，不是skill

> **类比**：command 是"详细作业指导书"（写满了步骤/检查点/回路），primary agent 是"操作工"（按指导书操作），子 agent 是"专用工具"（被操作工调用）。指导书是我们的核心——换个操作工也能按指导书干。

### 5.6 skill 可见性隔离

每个agent通过 `permission.skill` 只看到自己的skill：
```yaml
dws-designer: skill: { "dws-design-skill": allow, "*": deny }  # 看不到coder的
dws-coder:    skill: { "dws-coding-skill": allow, "*": deny }  # 看不到designer的
```

### 5.7 coder 动作边界（深入本质后定）

```
A. 读TS某规则（输入）
B. 理解设计意图+字段加工逻辑
C. 写SQL/DDL（核心产出）
D. 调执行脚本（传SQL+账号，不干等）← 执行等待由脚本承担，不占coder上下文
E. 拿结构化结果（成功/失败+报错摘要+行数+主键检查）
F. 失败→在自己上下文理解报错+改SQL ← E必须在coder（代码+报错同上下文改最快）
G. 成功→落盘
```

- coder 调执行脚本但**不直接连库**（避免多规则独立上下文下的执行风险）
- DDL/ETL执行顺序由**脚本管**（coder只产文件）
- 跨规则顺序由**orchestrator管**（串行编排，R1完成才调R2）

### 5.8 关键原则：什么用agent，什么用脚本

> **只有"上下文隔离有收益 + 需要 AI 理解"的才用 agent。确定性逻辑用脚本，编排逻辑留 orchestrator。**

### 5.9 脚本/工具组织（整体安装形态）

> 整个设计开发能力（agent + skill + 脚本 + 格式文档）作为一个整体，统一安装到 `~/.config/opencode/`。不存在"项目目录"假设——用户在自己的数据开发任务里使用。

**脚本跟着主要使用者走，放各自 skill 的 references/**：

| skill | 知识文档 | 脚本（references/*.py） |
|-------|---------|----------------------|
| dws-design | 设计方法论/命名规范/最佳实践/分段规则 | precheck（预检）、validate_ts（TS校验） |
| dws-coding | 编码规范/ETL模板 | validate_sql（静态检查）、execute（执行+机械检查）、check_consistency（一致性）、export（导出） |

**调用方式**：
- agent 调脚本：opencode 加载 skill 时**自动注入 skill 基目录**（绝对路径），agent 通过 `python <基目录>/references/xxx.py` 调用。不需要 dws-run 中转、不需要环境变量。
- command 不直接调脚本（路径定位不可靠），由 orchestrator（agent）调。

**内部辅助库**（被脚本 import，不直接暴露给 agent）：
- dws_preprocessor.py（DWS语法预处理，被 validate_sql 用）等 → 放对应 skill 的 references/ 里

**不要的**：~~dws-run（中转层）~~、~~独立 scripts/ 目录~~、~~.ts 工具包装~~、~~shared skill~~

> **部署约定**：整体安装到 `~/.config/opencode/`（agents/skills/commands 是 opencode 原生加载；脚本跟 skill 走；格式文档 agent read 获取）。唯一需要用户配置的是 Python 环境 + 数据库连接。

---

## 六、用户使用方式

### 6.1 设计开发段不定义 primary agent

设计开发段提供子 agent + skill + 脚本 + command，**编排逻辑沉在 command 里**。由项目的 primary agent（或内置 build）触发 command 执行编排。

### 6.2 使用流程

```
1. 在任意 primary agent 下（项目主agent / 内置build）
2. /new-pipe @mapping.xlsx @RS.md（command触发）
3. primary agent 按 command 指令执行编排：
   预处理→调designer产TS→⏸️闸口①（question弹确认）
4. 用户同会话确认/介入（长流程同会话对话）
5. primary agent 继续：调coder按规则螺旋→调导出脚本
6. 完成，产出TS+SQL/DDL+制品
```

> **关键**：编排逻辑（各种 loop / 流程控制 / 质量保障回路）全在 command + 子 agent + 脚本里，primary agent 只是执行者。换个 primary agent 也能跑。

### 6.3 段间交接：靠 spec 文件，段间解耦

| 交接 | 文件 |
|------|------|
| RS生成→设计开发 | RS文档+mapping → rs_input.json |
| 设计开发→测试 | ts.json + SQL/DDL + 制品 |
| 设计开发→运维 | 制品（术加/LTS/DQ） |

orchestrator 不关心 RS 谁产的，只读 rs_input.json。

---

## 七、关键架构决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | TS是制品包(ts.md+ts.json)，非单文档 | 300+字段进md会爆炸；json按规则切片实现上下文隔离 |
| 2 | TS以规则为核心实体，场景是属性 | 场景与规则对应不固定，以规则为锚点 |
| 3 | 字段内嵌规则，按rule_code分组 | 切片=取一个规则，真正上下文隔离 |
| 4 | design_logic=自然语言口径，不含SQL | SQL归coder翻译；自然语言便于闸口①人确认 |
| 5 | 砍掉细TS独立文档 | 消费者不足，字段逻辑落SQL注释 |
| 6 | 编排逻辑沉在command里，不定义自己的primary agent | 编排是设计开发方案包的核心（各种loop/流程/质量保障），沉在command里让任意agent执行；不和项目主agent冲突，没有主agent用build也能跑 |
| 7 | 核心子agent只2个(designer/coder) | 只有"上下文隔离有收益+需AI"才用agent；tester/exporter/预处理是脚本 |
| 8 | tester降级为脚本 | UT是机械检查（跑通/主键不发散），不需AI |
| 9 | 报错理解+改在coder | 代码+报错同上下文改最快 |
| 10 | coder调执行脚本不直接连库 | 避免多规则独立上下文执行风险 |
| 11 | 执行顺序脚本管，跨规则顺序orchestrator管 | coder只产文件 |
| 12 | 只有2个skill(design/coding)，无shared | skill本质=需加载到上下文的知识；格式文档read、脚本bash |
| 13 | skill按permission隔离 | 每个agent只看自己的skill |
| 14 | command是注入agent的指令模板 | 机制确认：command正文=prompt，agent字段指定执行者 |
| 15 | command只写差异+输入，基本流程在orchestrator | command是任务单，orchestrator是执行者 |
| 16 | 多流程段工具，段间靠spec交接 | 每段一个primary，段间解耦 |
| 17 | F表+I视图成对 | I=F镜像，固定模式，稳定消费接口 |
| 18 | 螺旋回路当前残缺(段1自动/段2-3人工)，保留扩展空间 | 术加2.0支持MCP后段3可接入 |
| 19 | 只有闸口①(TS后人审方向)，无闸口② | 代码正确性靠螺旋回路保证；代码review是段外合入gate(committer做)，不阻塞agent流程 |
| 20 | 制品能力是适配器模式 | 核心产平台无关中间表达，平台变化只改适配器，核心不受影响 |
| 21 | 螺旋回路理想是平台执行DML，当前直连库是绕过 | 平台是执行者，直连库是过渡手段，验证不了平台调度正确性 |
| 22 | designer/coder必须合并成一个段（不分成独立两段） | 返工闭环/闸口即时调整/TS活契约/认知连贯；"一体"=不向外交接的工作单元，非一个agent实例 |
| 23 | 质量保障：每产出后检查点+不通过回最近产出者重做≤3轮 | AI产出不稳定(随机/判断错/不合规)，靠多层检查层层把关；越后确定性越强 |
| 24 | 编码中返工简化（不设ABC复杂机制） | 实战中编码中返工不多，真实大量返工在测试后(跨段)；低频场景不值得建复杂机制 |
| 25 | TS校验=脚本+AI结合 | 结构完整/字段覆盖/血缘用脚本查(确定性)，设计合理性用AI查 |
| 26 | 脚本跟着skill走（references/），去掉dws-run | opencode加载skill时注入基目录，agent bash调；脚本归主要使用者的skill；不复杂化不中转 |
| 27 | 整体安装到~/.config/opencode/，无项目目录假设 | 能力打包整体安装，用户在自己任务里用；agent/skill/command原生加载，脚本跟skill走 |

---

## 八、待落地清单

### 已完成（定义层）

| # | 产出 | 文档 |
|---|------|------|
| 1 | TS制品包格式 | `docs/specs/ts-format.md` + 样板 |
| 2 | RS输入规范（草案，待对接） | `docs/specs/rs-input-format.md` + `docs/templates/RS模板.md` |
| 3 | 文件结构规范 | `docs/architecture/project-structure.md` |
| 4 | 架构定义（本文档） | `docs/architecture/architecture.md` |

### 待做（实现层）

| # | 改动 | 依赖 |
|---|------|------|
| 5 | 定义领域agent（designer/coder 的 agents/*.md） | 本文档 |
| 6 | 写2个skill（design-skill/coding-skill） | 5 |
| 7 | 重写command（/new-pipe等） | 5 |
| 8 | 输入预处理工具（excel_parser扩展+RS提取+预检合并） | RS格式定稿 |
| 9 | 执行脚本（连库跑SQL+机械检查，多账号） | 5 |
| 10 | 导出脚本（SQL+TS→制品中间表达） | ②责任人协同 |
| 11 | 补permission deny规则（三条红线落地） | 5 |
| 12 | 现有skill内容映射到新2个skill | 6 |
| 13 | 跑示例回归验证 | 5-12 |
| 14 | 维护内网差异清单 | 13 |

### 待对接（跨人/跨团队）

| # | 事项 | 对接方 |
|---|------|--------|
| A | RS最终格式（md/JSON/YAML） | 需求agent责任人 |
| B | analyzer现状spec与TS格式拉通 | analyzer责任人 |
| C | 制品中间表达格式（exporter产出） | ②制品能力责任人 |

---

## 九、待细化的盲区（实现时展开）

> 以下在设计层标注为盲区，不现在展开（避免过早设计），实现时细化。

1. **闸口①具体内容**：question弹窗给用户看什么（TS摘要？哪些重点？）、用户怎么回复（选项/自由文本）
2. **跨规则一致性检查**：orchestrator查什么（字段覆盖/命名一致/血缘完整/审计字段）、怎么查（静态脚本/AI判断）
3. **错误处理/失败恢复**：→ **质量保障体系已设计**（§5.4：检查点+重做回路）；预处理失败=预检拦截
4. **designer大表分段产出**：按场景分段的具体编排（先骨架→逐场景→回填），是agent行为设计
5. **执行脚本的优化方案**：coder调执行脚本的同步/异步/后台机制
6. **评审环节**：纯静态检查→脚本；需AI判断→临时调general subagent

---

## 十、对15论点的修正（design-dev-discussion-points.md）

| 论点 | 状态 | 说明 |
|---|---|---|
| 1（设计开发一体） | 演进 | "一体"由主agent编排+子agent隔离+spec交接实现 |
| 2（TS分粗细） | 修正 | 细TS取消；TS（原粗TS）做到字段分配级+自然语言逻辑 |
| 3（闸口①在粗设计后） | 保留 | question弹确认 |
| 4（细设计编码一体） | 修正 | 细设计消融进编码；细TS投影文档取消 |
| 5（规范是编码的事） | 保留 | 规范约束在coder |
| 6（编码是基础） | 保留 | — |
| 7（spec分层前置/投影） | 修正 | 投影spec(细TS)取消；前置spec(RS/TS)强化为机读schema |
| 8（四件套） | 保留+细化 | 术加/LTS/DQ本机只产出，运行验证在内网 |
| 9（平台协同+三红线） | 保留 | 红线靠permission兜底 |
| 10（代码稳定vs数据准确） | 保留+细化 | 代码稳定当前=段1通过（螺旋残缺） |
| 11（螺旋回路） | 修正 | 段1自动/段2-3人工（过渡），术加2.0后扩展 |
| 12（新建vs优化） | 保留 | 优化场景本次挂起 |
| 13（代码理解独立） | 保留 | analyzer独立建仓 |
| 14（spec交接） | 保留+强化 | RS/TS演进为机读JSON Schema |
| 15（能力矩阵） | 保留 | 实现方式调整，能力归属不变 |

---

*本文档为唯一架构文档，随落地进展更新。格式契约见 docs/specs/。*
