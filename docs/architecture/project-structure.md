---
status: active
last_reviewed: 2026-07-28
---

# 项目文件结构规范

> 本文定义设计开发 Agent 仓库的**大目录标准**：什么东西放在哪里。
> 核心原则：**按"性质"分目录，不按"来源"分。架构规范与用例产出严格分开。**

---

## 一、顶层结构总览

```
design-dev-agent/
├── docs/                设计文档（架构规范 + 格式定义 + 模板 + 产出示例）
├── commands/            运行时：command（用户发起流程的编排剧本）
├── skills/              运行时：skill（设计开发能力实现）
├── mcp-servers/         运行时：MCP server（连接层）
├── .opencode/           运行时：opencode 项目级配置（hooks/scripts/agents）
├── eval-suite/          工程能力：评测套件（针对 skill 的独立评测）
├── tests/               工程能力：单元测试
├── CLAUDE.md            项目入口（新会话先读）
├── README.md
├── requirements.txt     Python 依赖
└── pytest.ini
```

---

## 二、各目录职责边界

### `docs/` —— 设计文档区

**放什么**：给人读的文档（架构理念、格式规范、模板、产出示例）。
**不放什么**：可执行代码、运行时配置。

```
docs/
├── architecture/    架构（唯一架构文档 + 文件结构 + 论点历史）
│   ├── architecture.md                   ⭐ 唯一架构文档
│   ├── project-structure.md              ← 本文件
│   └── design-dev-discussion-points.md   15论点（历史推理，部分已演进）
│
├── specs/           格式规范（具体长什么样）
│   ├── ts-format.md        TS制品包格式（ts.json + ts.md 结构定义）
│   └── mapping-format.md   RS输入格式（Excel mapping 6 sheet 说明）
│
├── templates/       制品模板（四件套 Excel 模板）
│   ├── execution-tasks.xlsx
│   ├── schedule-tasks.xlsx
│   ├── product-template.xlsx
│   ├── multi-scenario-test.xlsx
│   └── examples/          模板填写案例
│
└── output/          产出示例（skill 运行时固定产出目录）
    └── dwl_con_pu_any_f/  标准参考示例（新结构样板）
```

**关键区分**：
- `architecture/` = **为什么**（架构理念、决策记录、论点推理）
- `specs/` = **是什么**（格式定义、字段结构、契约）
- `templates/` = **用什么**（Excel 模板，填充用）
- `output/` = **产出长啥样**（跑出来的实际示例）

> ⚠️ `docs/output/` 是 skill 运行时的固定产出目录（路径约定，skill 硬编码），**不改动路径**。示例内容保持为新结构样板（旧的 design.md/analyzer 残留已清理）。

---

### `commands/` —— 运行时·编排剧本

**放什么**：用户发起流程的 command（`.md`），定义 agent 编排顺序。
**当前**：`design.md` / `ulw-pipe.md` / `ulw-optimize.md`（旧版，待随重构重写）。

---

### `skills/` —— 运行时·能力实现

**放什么**：设计开发段的 skill（`SKILL.md` + `references/` + `run.py`）。
**当前**：9 个 skill（designer/coder/reviewer/code-reviewer/tester/exporter/optimizer/optimizer-coder/shared）。

> skill 内部结构（references 里 .py 和 .md 混放、shared 重复等）**留给 skill 重构时单独整改**，本次不碰。

---

### `mcp-servers/` —— 运行时·连接层

**放什么**：MCP server（连接外部系统的桥）。
**当前**：`postgresql-executor/`（连开发环境 DWS，螺旋回路必需）。

---

### `.opencode/` —— 运行时·opencode 项目配置

**放什么**：opencode 项目级配置。
**当前**：
- `hooks/whitelist.yaml`（工具白名单）
- `scripts/verify_files.py`（文件校验脚本）
- 未来：`agents/`（领域 agent 定义，**待定义时再建**）

---

### `eval-suite/` —— 工程能力·评测套件

**放什么**：针对 skill 的独立评测系统（测试 skill 产出对不对）。
**性质**：独立工程能力，与 skill（被测对象）平级但分离。

```
eval-suite/
├── runner.py          评测执行入口（validate/run-all/execute）
├── opencode_client.py 调用 opencode 跑 skill
├── report.py          评测报告生成
├── validators/        校验器（8种：design/sql/export/review/content/artifact/golden_diff）
├── cases/             测试用例（输入 + 期望）
├── golden/            标准答案（golden output）
├── results/           评测结果
└── skills/            被测 skill（运行时注入）
```

**关键区分**：`eval-suite` 是**评测工具**，`skills` 是**被评测对象**。两者不混。

---

### `tests/` —— 工程能力·单元测试

**放什么**：skill 配套的 pytest 单元测试。
**当前**：8 个测试文件 + fixtures。

---

## 三、性质分类速查

不知道某个东西放哪时，按性质查：

| 性质 | 放哪 | 例子 |
|------|------|------|
| 架构理念/决策记录 | `docs/architecture/` | 刷新记录、论点 |
| 格式规范/契约定义 | `docs/specs/` | TS格式、mapping格式 |
| Excel 模板 | `docs/templates/` | 四件套模板 |
| 跑出来的产出示例 | `docs/output/` | dwl_con_pu_any_f |
| 用户发起流程的剧本 | `commands/` | ulw-pipe |
| 能力实现（SKILL.md+脚本） | `skills/` | designer/coder |
| 连接外部系统 | `mcp-servers/` | postgresql-executor |
| opencode 项目配置 | `.opencode/` | hooks/agents |
| 评测 skill 对不对 | `eval-suite/` | runner/validators |
| 单元测试 | `tests/` | test_*.py |

---

## 四、维护原则

1. **架构规范 ≠ 用例产出**：`docs/architecture` + `docs/specs` 是规范（人定义的），`docs/output` 是产出（跑出来的）。两者不互相污染——产出示例里不该有规范文档，规范文档不依赖具体产出。
2. **产出目录路径固定**：`docs/output/` 是 skill 硬编码的运行时约定，不改动路径，只清理内容。
3. **新增内容先查性质**：按 §三 速查表定位，不要随手放。
4. **过时即清理**：文档被新结构替代后，及时清理旧产物（如本次清理 design.md/analyzer残留），不留"以后再说"的债。

---

*本文档随项目结构演进更新。*
