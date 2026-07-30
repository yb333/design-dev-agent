# 设计开发 Agent

> 数据交付全流程（DDLC）中的**中游主力段**：一个 agent 连续完成「粗设计 → 细设计 → 编码 → UT」。

[![status](https://img.shields.io/badge/status-active-green)]() [![stage](https://img.shields.io/badge/stage-design_dev-blue)]()

---

## 这是什么

端到端数据交付流程：`需求 → [设计开发] → 测试 → 部署 → 运维`

**本项目只负责方括号里的设计开发段**——把 RS（需求 spec）转成 TS（技术 spec）+ 四件套制品（DDL/术加 ETL/LTS 调度/DQ 质量检查）。

详细定位见 [CLAUDE.md](./CLAUDE.md) 和 [架构文档](./docs/architecture/architecture.md)。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 MCP（连开发环境 DWS）
cd mcp-servers/postgresql-executor
npm install && npm run build
cp db-config.example.json db-config.json  # 填开发库连接

# 3. 跑测试
python -m pytest tests/ -v
```

## 项目结构

```
.
├── skills/                          # 9 个 skill（设计开发流程的实现）
│   ├── dws-pipeline-{designer,coder,reviewer,...}/
│   └── dws-run.py                   # skill 调度器
├── commands/                        # 3 个编排命令
│   ├── design.md / ulw-pipe.md / ulw-optimize.md
├── mcp-servers/
│   └── postgresql-executor/         # 连开发环境 DWS（螺旋回路必需）
├── docs/
│   ├── architecture/                # 架构（必读）
│   │   ├── architecture.md               # ⭐ 唯一架构文档
│   │   ├── project-structure.md          # 文件结构规范
│   │   └── design-dev-discussion-points.md  # 15 论点（历史推理）
│   ├── specs/                       # 格式契约（TS格式/RS输入/Mapping格式）
│   ├── templates/                   # 制品模板 + RS模板
│   └── output/                      # 产出示例（运行时目录约定）
├── eval-suite/                      # 评测套件（独立工程）
├── tests/                           # skill 配套测试
├── CLAUDE.md                        # ★ 新会话入口（必读）
└── requirements.txt
```

## 核心文档（按阅读顺序）

1. **[CLAUDE.md](./CLAUDE.md)** — 项目全局认知，新会话入口
2. **[架构文档](./docs/architecture/architecture.md)** — ⭐ 唯一架构文档（环境/四区/agent-skill-command/螺旋/决策）
3. **[产出示例](./docs/output/dwl_con_pu_any_f/)** — 跑一遍理解产出结构（ts.json/ts.md + 制品）

## 与其他系统的关系

- **上游**：需求 Agent（产 RS）—— 待建设
- **协作方**：代码理解 Agent（产现状 spec，优化场景输入）—— 独立仓
- **下游**：测试 Agent —— 待建设
- **宿主**：桌面客户端（DataGenie）—— 客户端仓

---

*本项目 2026-07 从 [ETL_opencode_ai](https://github.com/) 客户端仓拆分独立。*
