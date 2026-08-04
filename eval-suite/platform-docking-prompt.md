# 平台对接调研任务（给内网 agent）

> 你是一个对接调研员。目标是摸清"打通平台的脚本"需要什么输入，
> 对照本仓的产出（ts.json + SQL），定出两边对接的契约格式。
> **这是调研，不是写代码**——产出一份契约文档就完成任务。

---

## 全局规则（违反任意一条算失败）

1. **不要修改本仓任何代码文件**（.py / .md / .json 等）。你只读、只写一份新文件。
2. **不要凭记忆猜测**。所有结论必须基于你实际读到的文件内容。读到哪里引用到哪里。
3. **按步骤顺序执行**。每步有"完成标志"，标志没达成不要进入下一步。
4. **文件路径用相对路径**（相对项目根目录）。你在项目根目录下工作。
5. **一次只读一个文件**，读完总结要点再读下一个（节省上下文）。

---

## 第一步：理解我们这边的产出（ts.json 长什么样）

### 1.1 读 TS 格式定义

读文件：`docs/specs/ts-format.md`

重点找 `meta.schedule` 段的定义。它应该包含这些字段：
- `task_name`（任务名）
- `cron`（调度表达式）
- `project`（项目）
- `task_group`（任务组）
- `exec_params`（执行参数）
- `upstream`（上游依赖）
- `execution_platform`（执行平台标识）

**完成标志**：你能用一句话说清 `meta.schedule` 里有哪些字段、各自含义。

### 1.2 读真实产出样本

读文件：`10_project_deliver/dwb_trade_wide_f/ddlc_design_dev/ts.json`

这是一个真实跑出来的 ts.json。看三块内容：
- `meta.schedule`：看 task_name / cron / project / task_group 的实际值
- `meta.target`：看 f_table（目标物理表）和 i_view（目标视图）的 schema/table
- `rules`：看有几条规则，每条规则的 `target_table` / `exec_sequence` / `is_view_step`

**完成标志**：你能回答——这个资产的 task_name 是什么？有几条规则？有没有视图步骤？

### 1.3 读旧的 export 制品（参考用，不是标准）

读文件：`docs/output/dwl_con_pu_any_f/09_export/export_manifest.json`

这是**旧版 exporter** 产出的清单（旧 exporter 已删除，新 exporter 还没写）。
它揭示了平台**曾经**需要哪些字段。把这些字段全列出来：
- `task_name` / `job_name`（注意 Pjob_ 前缀）/ `project_name` / `task_group` / `cron_expr`
- `params`（注意参数名，可能是 V_CYCLE_ID 不是 P_CYCLE_ID）
- `upstream_tasks`（注意结构：source_table / schedule_task / exec_path / dep_job_params）
- `view_task_name` / `view_job_name` / `view_name`
- `target_table` / `target_table_short`

**完成标志**：你列出 manifest 里所有字段名，并标注哪些 ts.json 里直接有、哪些需要派生。

---

## 第二步：摸清内网平台脚本要什么

找到内网那个"打通平台的脚本"（Python 脚本）。

### 2.1 找到脚本

它可能在这些位置（按可能性排序）：
- 项目根目录下的某个 .py 文件
- 某个 `scripts/` 或 `tools/` 目录
- 你工作目录附近的某个独立目录

用 `find . -name "*.py"` 或问用户"平台脚本在哪"。

**完成标志**：你找到了脚本的完整路径。

### 2.2 分析脚本的输入

读这个脚本，搞清楚四件事：

**① 输入形态**：
- 命令行参数？（列出所有 argparse 参数）
- 读配置文件？（什么文件、什么格式）
- 读标准输入？

**② 输入字段清单**：
把脚本期望的所有输入字段列出来。格式：

| 字段名 | 类型 | 必填/可选 | 含义 | 从哪传进来 |
|--------|------|-----------|------|-----------|
| ...    | ...  | ...       | ...  | ...       |

**③ 它推到平台后创建什么**：
- 一个"任务"（task）？
- 一个"作业"（job）？
- 一个"调度"（schedule）？
- 还是多个？

**④ 认证/配置**：
- 连接信息从哪来？
- 需要什么环境变量或配置文件？

**完成标志**：你能完整说出"这个脚本接受什么输入、产出什么、需要什么配置"。

---

## 第三步：做字段映射表

基于第一步（我们有什么）和第二步（平台要什么），填这张表：

| 平台需要的字段 | 我们 ts.json 里的来源 | 状态 | 说明 |
|----------------|----------------------|------|------|
| task_name      | meta.schedule.task_name | 有 | 直接用 |
| job_name       | （没有）               | 需派生 | 旧 manifest 用 Pjob_ 前缀，需确认平台规则 |
| ...            | ...                   | ...  | ...  |

**状态分三类**：
- **有**：ts.json 里直接能取到
- **需派生**：ts.json 里没有，但能从已有信息推导（如 job_name = "Pjob_" + task_name）
- **完全没有**：ts.json 里没有也无法推导，需要 designer 补充或 exporter 让人填

**特别关注这些可能坑**：
- 参数名差异：我们用 `P_CYCLE_ID`，平台可能要 `V_CYCLE_ID`
- job_name 派生规则：Pjob_ 前缀是否通用？有没有例外？
- 多规则场景：tmp 中间表 + f 目标表 + i 视图，平台怎么组织成一个"任务"？
- upstream 结构：我们的 upstream 跟平台的 upstream_tasks 结构可能不同

**完成标志**：每个平台需要的字段，都能说出"从哪来"或"怎么派生"或"缺，需补"。

---

## 第四步：写契约文档

创建文件：`docs/specs/platform-contract.md`

**用下面的模板填**（不要自己发明结构，照着填）：

```markdown
# 平台对接契约

> 本文件是 design-dev-agent 仓 与 内网平台 skill 的对接权威。
> exporter 产出什么、平台 skill 消费什么，以本文件为准。

## 一、契约文件

- **文件名**：platform_manifest.json（或沿用旧名 export_manifest.json）
- **位置**：10_project_deliver/{资产名}/ddlc_design_dev/ 下，跟 ts.json 同级
- **产出方**：本仓的 exporter（待实现）
- **消费方**：内网平台 skill（待封装）

## 二、平台输入 Schema

| 字段名 | 类型 | 必填 | 含义 | 示例值 |
|--------|------|------|------|--------|
| （照第二步填） | | | | |

## 三、字段映射表

（照第三步填，三列：平台字段 / ts.json 来源 / 状态）

## 四、缺口清单（需派生或缺失的字段）

| 字段 | 派生规则 / 缺失原因 | 处理方案 |
|------|---------------------|----------|
| job_name | （如）"Pjob_" + task_name | exporter 自动派生 |
| ...  | ...                 | ...      |

## 五、多规则场景处理

（如果资产有多条规则 tmp→f→i，平台怎么组织：
- 一个任务含多个作业？
- 多个独立任务？
- 中间表是否需要单独调度？）

## 六、skill 对接约定

- 本仓 exporter skill 名称：（待定，如 dws-export）
- 内网平台 skill 名称：（待定，如 platform-push）
- 输入约定：内网 skill 读 {资产目录}/platform_manifest.json

## 七、未解决问题（调研中没搞清楚的）

（列出还需要人工确认的疑点）
```

**完成标志**：文件 `docs/specs/platform-contract.md` 创建完成，七个章节都填了（第七章可以为空）。

---

## 第五步：自检

回答以下问题，全部能答才算完成：

1. 平台脚本接受什么输入？（文件？参数？）
2. 平台需要哪些必填字段？
3. 这些字段里，ts.json 直接能提供的有几个？需要派生的有几个？完全缺失的有几个？
4. 参数名有没有差异（P_CYCLE_ID vs V_CYCLE_ID）？
5. job_name 怎么派生？
6. 多规则资产（tmp 中间表 + f + i 视图）平台怎么处理？
7. 有没有搞不清楚、需要人工确认的点？

**如果第七步有搞不清楚的点**，不要编答案——如实写进契约文档的"未解决问题"章节。

---

## 完成后

向调用方回报：
1. 契约文档路径：`docs/specs/platform-contract.md`
2. 一句话结论：平台要什么、我们缺什么、对接难度如何
3. 列出未解决问题（如果有）

不要修改任何本仓代码。不要写 exporter 代码。这次只调研、定契约。
