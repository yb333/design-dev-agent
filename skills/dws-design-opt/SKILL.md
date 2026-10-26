---
name: dws-design-opt
description: >-
  DWS ETL 优化模式设计工作流（add_field）。被 dws-designer agent 在【优化场景】加载
  （调用方 prompt 显式声明优化模式时）。身份与权限不变；工作流换成优化版：
  读 baseline_view + change_request，只写增量 design_decisions_opt.yaml，
  调 assemble_ts_opt 组装 ts.json（本次产出）。设计知识与工具路径引用 dws-design（不搬家）。
---

## ⚠️ 文件路径规则

本 skill 安装目录下没有 scripts/references 副本——**知识与工具都在 dws-design skill**，
按相对路径引用（本 skill 目录上三级即 skills/ 根）：
- 设计知识：`{skills根}/dws-design/references/`（incremental-playbook / complexity-playbook；分布键/分区/依赖类型标准在 dws-design SKILL §2 第4层）
- 组装脚本：`{skills根}/dws-design/scripts/assemble_ts_opt.py`
- 模板：本 skill 的 `assets/opt-decisions-template.yaml`
- 本 skill 专属知识：`references/opt-playbook.md`（落位取舍树 + 回刷决策树）

## 一、你与新建模式的四个不同

1. **只写增量，不写存量**：每个新增字段一条 decisions，存量一概不碰（重写存量=红线）。
2. **存量语义不补**：baseline 的主键/粒度/关联安全是空位——**不需要你补**（存量回归由
   SQL 围栏+UT 全量质检保障）；你只为**新 JOIN** 声明关联安全性（生产在跑不是新 JOIN 的理由）。
3. **围栏罩着你**：组装产物会被 fence_check 机器审计（越界/漏改硬阻断）。decisions 说什么，
   ts 就是什么——组装器是确定性的，你夹带不了任何东西，别试。
4. **Territory 禁读（输入面只有四件）**：baseline_view + change_request（含 placement_hints）+
   模板 + playbook。**archive/ts.json、archive/etl/*.sql、全量 mapping xlsx、全量 RS 一律不 Read**
   （脚本域材料——别名对照/落位预判/变更字段存量条目已全部预计算进 view 与 change_request；
   与新建「rs_input.json 不 Read」同一条纪律）。缺信息 → 上报调用方报 view 改进缺口，
   禁回读原文自行绕过。

## 二、单线工作流（五步）

### 1. 读输入
- `baseline_view.md`——老资产长什么样（**decisions 语言地图**：锚点[粒度/主键]·规则拓扑
  [源/JOIN·safety/读中间表]·**别名对照[SQL 实际别名=落笔权威]**·语义空位）。有值的判断位
  =真档原设计意图直接可用；▢ 空位=存量语义空位（不补，新 JOIN 现声明）。
- `change_request.json`——这次要加什么（业务说了什么；`new_source_table: true` = 新来源信号；
  **`placement_hints` = 每个新增字段的源表可见规则[直挂 direct_rules/穿中间表
  via_intermediate]预计算**——你落位取舍的起始材料）。
  **字段带 `decision` 标记 = 类型风险已人定（原始输入='直接复制'，勿推翻方向）——译守卫式
  转换 design_logic；`join_type_decisions` 段的处置=转换 → 对应 joins 必须声明 cast**；
  modify 条目已内联存量参考（old_type/old_expr=基线当前态，rules=旧口径所在规则）。
- RS 优化章节原文在 change_request.rs_opt_section——口径从这读

### 2. 落位决策（核心判断，一个）
新字段从源头到目标表走哪条路：直挂目标规则 / 穿中间表（中间表加列、多规则落位）。
起始材料=change_request.placement_hints（源表可见规则预计算——直挂候选/穿中间表候选
/新来源），取舍树见 `references/opt-playbook.md` §一。落位写进 decisions 的 placed_rules /
intermediate_tables——**这是围栏许可的边界，落错位会连锁漏改**。

### 3. 新 JOIN 声明（有新来源才做）——先取证后断言（与新建评估层同款纪律）
每个新 JOIN 必须带 join_safety（join_key_unique / strategy / reason），组装器硬拦三空：
strategy 空 / join_key_unique 缺结论 / **reason 空（断言必须有依据句）**。取证一次收口：
- change_request.eval_worksheet 是预填工作单（新源 join_condition 已预解析，`?` 行=键
  唯一性实测位），探针上下文已就绪：
  `python {skills根}/dws-design/scripts/explore.py --rs {build}/_internal/eval_context.json --eval`
  （stdin 只给 `?` 行答案：`别名|键|限定`；结构化预填行自动跑）
- 实测数字直贴 reason（如 `explore 实测 count=12000 distinct=12000 唯一`）；免实测声明
  （取一/开窗）工作单自动机械核对。
- 连不上库 → reason 标注「未实测（连不上库）」+ 输入声明依据（不阻断，宁放过）；
  **有疑点不落笔**——随回复上报（疑似方向一句），与新建评估层同款。

### 4. 回刷判断
按 opt-playbook §二决策表：全量基线→无需回刷（backfill: none）；增量基线→pending
（闸口①'人选拿）。RS 优化章节写了意向就预填。

### 5. 写 decisions + 组装
```bash
python {skills根}/dws-design/scripts/assemble_ts_opt.py \
  --ts-baseline {arc}/ts.json \
  --decisions {build}/_internal/design_decisions_opt.yaml \
  --output {arc_tmp}/ts.json（全量态直产临时档案）
```
模板骨架读 `assets/opt-decisions-template.yaml`（必填项见模板注释；缺了组装器 fail loud）。
组装成功即回报调用方（围栏由 pipe 跑，不是你跑）。

## 三、发现存量问题时

想顺手修存量（口径错/关联发散/声明漂移）——**不许直接改**。回报调用方走
【建议追加的变更】通道（闸口①'人确认后进 change_request）。这是唯一的路。
涉及"改输入"的终止型问题（mapping/RS/源端要修）同样**不问**——停手上报编排者
（带完整后果问人），问人分流判据同 dws-design SKILL。

## 四、验收口径

- decisions 每条与 change_request 字段一一对应（不多不少——多了是夹带，少了是漏接）
- 新 JOIN 全部带 safety 且 **reason 有依据**（实测数字/输入声明/未实测标注）；回刷意向已按决策表填
- 产出：`_internal/design_decisions_opt.yaml` + `ts.json`（脚本写）
