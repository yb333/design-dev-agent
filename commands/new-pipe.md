---
description: DWS ETL 设计开发全流程（预处理→设计→闸口①→编码→闸口②）
agent: dws-engineer
---

以 dws-engineer 身份执行新建交付全流程：用 Skill tool 加载 `new-pipe` skill 并逐字执行其剧本。**模式: 新建**（本命令已定，$ARGUMENTS 免传）。任务参数（$ARGUMENTS，单行分号式，与总控契约同构）：
mapping: /path/xxx.xlsx; rs: /path/RS_xxx.md; [交互: non-interactive]（资产名从输入推导勿传）
