---
name: dws-design-opt
description: >-
  DWS ETL 优化模式设计工作流（add_field）。被 dws-designer agent 在【优化场景】加载
  （调用方 prompt 显式声明优化模式时）。身份与权限不变；工作流换成优化版：
  读 baseline_view + change_request，只写增量 design_decisions_opt.yaml，
  调 assemble_ts_opt 组装 ts_v2。设计知识与工具路径引用 dws-design（不搬家）。
---

## ⚠️ 文件路径规则

本 skill 安装目录下没有 scripts/references 副本——**知识与工具都在 dws-design skill**，
按相对路径引用（本 skill 目录上三级即 skills/ 根）：
- 设计知识：`{skills根}/dws-design/references/`（incremental-playbook / complexity-playbook / design-guide）
- 组装脚本：`{skills根}/dws-design/scripts/assemble_ts_opt.py`
- 模板：本 skill 的 `assets/opt-decisions-template.yaml`
- 本 skill 专属知识：`references/opt-playbook.md`（落位取舍树 + 回刷决策树）

## 一、你与新建模式的三个不同

1. **只写增量，不写存量**：每个新增字段一条 decisions，存量一概不碰（重写存量=红线）。
2. **存量语义不补**：baseline 的主键/粒度/关联安全是空位——**不需要你补**（存量回归由输出
   对比保障）；你只为**新 JOIN** 声明关联安全性（生产在跑不是新 JOIN 的理由）。
3. **围栏罩着你**：ts_v2 会被 fence_check 机器审计（越界/漏改硬阻断）。decisions 说什么，
   ts_v2 就是什么——组装器是确定性的，你夹带不了任何东西，别试。

## 二、单线工作流（五步）

### 1. 读输入
- `baseline_view.md`——老资产长什么样（规则清单/写入类型/增量材料/血缘/warnings/语义空位）
- `change_request.json`——这次要加什么（业务说了什么；`new_source_table: true` = 新来源信号）
- RS 优化章节原文在 change_request.rs_opt_section——口径从这读

### 2. 落位决策（核心判断，一个）
新字段从源头到目标表走哪条路：直挂目标规则 / 穿中间表（中间表加列、多规则落位）。
取舍树见 `references/opt-playbook.md` §一。落位写进 decisions 的 placed_rules /
intermediate_tables——**这是围栏许可的边界，落错位会连锁漏改**。

### 3. 新 JOIN 声明（有新来源才做）
每个新 JOIN 必须带 join_safety（join_key_unique / strategy / reason）——组装器强制。
不确定键唯一性时可调 explore 试算（工具在 dws-design/scripts）。

### 4. 回刷判断
按 opt-playbook §二决策表：全量基线→无需回刷（backfill: none）；增量基线→pending
（闸口①'人选拿）。RS 优化章节写了意向就预填。

### 5. 写 decisions + 组装
```bash
python {skills根}/dws-design/scripts/assemble_ts_opt.py \
  --ts-baseline {deliver}/_internal/ts_baseline.json \
  --decisions {deliver}/_internal/design_decisions_opt.yaml \
  --output {deliver}/ts_v2.json
```
模板骨架读 `assets/opt-decisions-template.yaml`（必填项见模板注释；缺了组装器 fail loud）。
组装成功即回报调用方（围栏由 pipe 跑，不是你跑）。

## 三、发现存量问题时

想顺手修存量（口径错/关联发散/声明漂移）——**不许直接改**。回报调用方走
【建议追加的变更】通道（闸口①'人确认后进 change_request）。这是唯一的路。

## 四、验收口径

- decisions 每条与 change_request 字段一一对应（不多不少——多了是夹带，少了是漏接）
- 新 JOIN 全部带 safety；回刷意向已按决策表填
- 产出：`_internal/design_decisions_opt.yaml` + `ts_v2.json`（脚本写）
