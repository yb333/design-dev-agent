# 设计开发 Agent

数据交付全流程（DDLC）中游段：一个 agent 连续完成「粗设计 → 细设计 → 编码 → UT」——输入 RS + mapping，输出 TS 制品包 + 四件套（DDL / 术加 ETL / LTS 调度 / DQ）。

- **使用本段交付**：读 [docs/user-guide.md](./docs/user-guide.md)（内网仓根目录同步为 `使用指南-设计开发段.md`）
- **维护本仓**：读 [AGENTS.md](./AGENTS.md)（当前实际结构 + 约定，唯一权威）
- **程序化对接**（总控拉起）：读 [docs/integration-contract.md](./docs/integration-contract.md)
