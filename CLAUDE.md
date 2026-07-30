# 设计开发 Agent · 项目指令

> **本文件是新会话的入口**。任何新窗口/新 agent 打开本仓，先读本文件。
> 它定义了：这是什么、当前状态、架构共识、下一步要做什么。

---

## 这是什么

**设计开发 Agent**——数据交付全流程（DDLC）中的**中游主力段**。

端到端流程：`需求 → [设计开发] → 测试 → 部署 → 运维`，本项目只负责方括号里的**设计开发段**。

设计开发段 = 一个 agent 连续完成「**粗设计 → 细设计 → 编码 → UT**」，中间不拆断、不交接，但在粗设计后有闸口①人确认方向。

### 边界（三条红线 · 论点 9）

- **语义判断不自主**：数据合理性、模式选择、字段语义 → 给材料，人定
- **推到生产不自主**：写生产库、推规则上线 → 生成制品，人推
- **重写不自主**：优化推倒重来 → 只精确修改，想重写走新建

### 输入 / 输出

| 场景 | 输入 | 输出 |
|---|---|---|
| **新建** | RS（需求 spec，1 个）| TS 制品包（ts.json+ts.md）+ 四件套制品（DDL/术加/LTS/DQ）|
| **优化** | 变更 RS（增量）+ 现状 spec（代码理解 Agent 产，2 个）| 同上（修改后的版本）|

**四件套制品**：DDL（建表）/ 术加 ETL 制品（执行平台运行+捞日志）/ LTS（调度配置）/ DQ（质量检查 SQL，只产出不管运行）

---

## 当前状态（2026-07）

### 已有（从客户端仓迁移而来）

| 内容 | 路径 | 说明 |
|---|---|---|
| 9 个 skill | `skills/dws-pipeline-{designer,coder,reviewer,code-reviewer,tester,exporter,optimizer,optimizer-coder,shared}` | 设计开发流程的实现 |
| skill 调度器 | `skills/dws-run.py` | `dws-run <skill> <action>` 入口 |
| 3 个 command | `commands/{design,ulw-pipe,ulw-optimize}.md` | 用户发起流程的编排剧本（旧版，待重写）|
| 1 个 MCP | `mcp-servers/postgresql-executor/` | 连开发环境 DWS（螺旋回路必需）|
| 评测套件 | `eval-suite/` | 针对 skill 的独立评测系统（runner/validators/cases/golden）|
| 架构文档 | `docs/architecture/` | 见下方「核心文档」|
| 格式规范 | `docs/specs/` | TS格式、mapping格式定义 |
| 产出示例 | `docs/output/dwl_con_pu_any_f/` | 新结构样板（ts.json + ts.md + 制品）|
| 模板 | `docs/templates/*.xlsx` | 四件套制品的 Excel 模板 |
| 测试 | `tests/` | skill 配套 pytest |

> **文件结构规范**见 `docs/architecture/project-structure.md`（各目录职责边界 + 性质分类速查）。

### 不属于本项目（已剥离）

- **代码理解 Agent**（analyzer）：在独立仓开发，本项目优化场景时**调用**它产出的现状 spec
- **excel-io MCP**：留客户端仓（通用工具，多段共用）
- **桌面客户端**（web/）：留客户端仓
- **需求 / 测试 / 运维 Stage**：由其他人负责

### 待重构（方向已定，见架构文档）

迁移时保留了客户端仓的现状。架构方向已定稿，见 `docs/architecture/architecture.md`。核心：

1. **去掉 oh-my-opencode**，自定义领域 agent（orchestrator + designer/coder）
2. **TS 是制品包**（ts.json 机读 + ts.md 人读），以规则为核心实体
3. **核心子 agent 只2个**（designer/coder），tester/exporter/预处理是脚本
4. **spec 协议层**：RS/TS 演进为机读格式（TS 已定，RS 待对接）
5. **双环境**：本仓产出+近似验证，内网验证对接平台+模型兼容

详见架构文档 §五（agent/skill/command）、§七（决策记录）、§八（待落地清单）。

---

## 架构共识

本项目是 DDLC Pipeline 的设计开发段。**完整架构见 `docs/architecture/architecture.md`**（唯一架构文档），含：
- 环境事实（双环境/单向数据流）
- 四区组件结构（主体能力/制品能力/评测体系/编排层）
- agent/skill/command 架构（orchestrator + designer/coder + 脚本 + command）
- 螺旋回路与现实约束
- 用户使用方式
- 18条关键决策记录 + 待落地清单 + 待细化盲区

**核心范式**：spec-first（RS/TS 结构对齐，架构级硬要求）

---

## 核心文档（按优先级读）

新会话**必读**（只 3 个，精简入口）：

1. **本文件**（CLAUDE.md）—— 全局认知
2. **`docs/architecture/architecture.md`** —— ⭐ **唯一架构文档**（环境/四区/agent-skill-command/螺旋回路/决策记录/待落地清单）
3. `docs/output/dwl_con_pu_any_f/` —— 跑一遍这个示例，理解产出结构

选读（按需）：
- `docs/architecture/project-structure.md` —— 文件结构规范（各目录职责边界，不知道放哪时查这个）
- `docs/specs/ts-format.md` —— TS制品包格式定义（ts.json + ts.md 结构）
- `docs/specs/rs-input-format.md` —— RS输入规范（⚠️草案，RS格式待对接定稿）
- `docs/architecture/design-dev-discussion-points.md` —— 15个论点（⚠️部分已被architecture.md演进，历史推理参考）

---

## 开发命令

### Python 环境

```bash
pip install -r requirements.txt
python -m pytest tests/ -v          # 跑测试
python -m pytest scripts/test_*.py  # 跑特定测试
```

### skill 调用（开发期，跨平台）

```bash
# 执行 skill 脚本
dws-run designer excel_parser --input mapping.xlsx --output docs/output/
dws-run coder sql_validator --ddl-dir docs/output/{table}/04_ddl --output ...

# 读 skill 参考文件
dws-run designer read references/design-template.md
dws-run designer path    # 输出 skill 目录
```

> **注**：`dws-run` 在客户端仓里通过 Tauri 注册到 PATH。本仓独立后，开发期需要手动配置（待新会话处理）。

### MCP server（postgresql-executor）

```bash
cd mcp-servers/postgresql-executor
npm install
npm run build
# 配置：cp db-config.example.json db-config.json，填开发库连接
```

---

## 下一步（待落地清单）

详见 `docs/architecture/architecture.md` §八（待落地清单）。当前阶段：

- **已完成（定义层）**：TS格式、RS输入草案、文件结构、架构定义
- **待做（实现层）**：定义agent（orchestrator/designer/coder）→ 写2个skill → 重写command → 预处理/执行/导出脚本 → permission deny → 回归验证
- **待对接**：RS最终格式（需求agent责任人）、analyzer拉通、制品格式（②责任人）

**挂起项**：优化场景（analyzer对接）、评审形态（倾向静态检查+闸口）

---

## 约定

- **代码风格**：Python snake_case，skill 配置见各 SKILL.md
- **提交规范**：`feat/fix/refactor/docs: 描述`（中文或英文）
- **路径约定**：所有产出在 `docs/output/{target_table}/` 下（运行时约定，skill 硬编码）
- **架构演化**：涉及架构理念变更时，遵循演化流程（参考客户端仓的 evolution-process.md）

---

*本文件随项目演进持续更新。最后更新：2026-07-29（架构文档合并为唯一 architecture.md，整体回顾完成）*
