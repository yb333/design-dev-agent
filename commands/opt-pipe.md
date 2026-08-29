---
description: DWS ETL 优化全流程（入口→输入校验→设计→围栏→闸口①→编码→SQL围栏→UT→闸口②→制品→归档）
agent: dws-engineer
---

以 dws-engineer 身份执行优化交付全流程：用 Skill tool 加载 `opt-pipe` skill 并逐字执行其剧本。任务参数（$ARGUMENTS，单行分号式，与总控契约同构）：
模式: 优化; mapping: /path/需求包目录; rs: /path/RS_xxx.md; [交互: non-interactive]（资产名从输入推导勿传）
