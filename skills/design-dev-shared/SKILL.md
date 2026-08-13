---
name: design-dev-shared
description: >-
  设计开发公共代码库（dws_db/config_paths/resolve_appid 等共享脚本）。
  被 new-pipe command 在流程开始时加载，提供脚本目录定位锚点（location 注入）。
  不含工作指导，仅用于路径锚定 + 公共脚本暴露。
slash: false
---

# 设计开发公共库

本 skill 是设计开发 agent 的公共代码库，**不是工作指导**，body 极简。

## 用途：路径锚定

被 new-pipe command 在流程开始时加载，用于定位所有脚本目录。加载后 opencode 注入的 `location`（本 SKILL.md 绝对路径）= `.../skills/design-dev-shared/SKILL.md`，由此推算：

- **SHARED_SCRIPTS** = location 同级 `/scripts`（即 design-dev-shared/scripts）
- **DESIGN_SCRIPTS** = location 上三级 `/dws-design/scripts`（上三级 = skills 目录）
- **CODING_SCRIPTS** = location 上三级 `/dws-coding/scripts`

## 公共脚本（SHARED_SCRIPTS 下）

- `dws_db.py`：连库能力（DBExecutor 抽象 + PsycopgExecutor）
- `config_paths.py`：config 文件路径解析（opencode_root 多候选探测）
- `resolve_appid.py`：按 schema 反查 appid（CLI）
