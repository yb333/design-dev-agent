---
description: DWS ETL 设计开发全流程（预处理→设计→闸口①→编码→闸口②）
agent: build
---

你是设计开发流程的执行者。按以下步骤执行完整的设计+编码全流程。

用户输入：$ARGUMENTS（资产名或 mapping/RS 文件路径）

---

## 产出目录结构

所有产出放在 `10_project_deliver/{资产名}/ddlc_design_dev/` 下：

```
10_project_deliver/{资产名}/              ← 可能由别的 agent 创建，不存在则你建
└── ddlc_design_dev/                      ← 你建（标识产出范围）
    ├── ts.json                           ← 设计产出（对外）
    ├── ts.md                             ← 设计产出（人读）
    ├── select/                           ← 编码产出（coder 产的 SELECT）
    │   └── R0001_select.sql
    ├── ddl/                              ← 编码产出（脚本生成的 DDL）
    │   └── create_table_xxx.sql
    └── _internal/                        ← 过程产物
        ├── rs_input.json                 ← 预处理产出
        ├── design_decisions.yaml         ← 设计决策
        └── ut_report.txt                 ← UT 执行报告（如有数据库）
```

> 下文用 `{deliver}` 代指 `10_project_deliver/{资产名}/ddlc_design_dev`。
> **资产名**从 RS 资产信息或 mapping 目标表推导。
> 脚本路径用 glob 找：`glob: **/dws-design/references/preprocess.py`。

---

# ════════ 设计段 ════════

## 步骤 1：预处理（转换 + 校验，分开执行）

从用户输入识别 mapping 文件（.xlsx）和 RS 文件（.md）。

**步骤 1a：转换**（mapping + RS → rs_input.json）

```bash
python {scripts}/preprocess.py \
  --mapping {mapping路径} \
  --rs {RS路径} \
  --output {deliver}/_internal/rs_input.json
```

**步骤 1b：校验**（检查 rs_input.json 完整性）

```bash
python {scripts}/precheck.py \
  --input {deliver}/_internal/rs_input.json
```

**校验返回码**：
- 0（PASS）→ 继续
- 1（WARNING）→ 显示警告，问用户是否继续
- 2（INCOMPLETE）→ 停止，让用户修改**源文件**（mapping.xlsx 或 RS.md）后重新执行 1a+1b

> ⚠️ 用户修改的是 mapping.xlsx 或 RS.md（源文件），不是 rs_input.json（产物）。

---

## 步骤 2：调 dws-designer 产出 TS

预处理通过后，用 Task 调用 dws-designer。

designer 内部会自行完成"产 design_decisions.yaml → 调 assemble_ts.py 组装 ts.json/ts.md"。

```
Task(
  subagent_type="dws-designer",
  description="产出TS制品包",
  prompt="读取 {deliver}/_internal/rs_input.json，产出 TS 制品包（ts.json + ts.md）到 {deliver}/。"
)
```

designer 完成后用 `ls` 验证 `{deliver}/` 下已生成 ts.json + ts.md。

---

## 步骤 3：闸口①（人确认设计方向）

> **非交互模式**（如 `opencode run` 自动测试）：跳过闸口，打印摘要后直接进入编码段。

**交互模式**：必须暂停等用户确认。用 question 展示设计摘要：

```
## 设计完成，请确认方向

### 设计摘要
- **目标表**: {schema}.{table}（{中文名}）
- **规则数**: {N} 个
- **字段统计**: 业务 {N} + 审计 4 = 总计 {N}

### 规则概览
{每个规则的 rule_name + design_intent}

请选择：
- ✅ 确认设计，进入编码
- ✏️ 需要修改（说明哪里要改）
- ❌ 放弃
```

**用户确认** → 进入编码段。
**用户要改** → 回步骤 2 重新调 designer。

---

# ════════ 编码段 ════════

## 步骤 4：生成 DDL

调脚本从 ts.json 自动生成 DDL：

```bash
python {scripts}/assemble_ddl.py --ts {deliver}/ts.json --outdir {deliver}/ddl
```

---

## 步骤 5：逐规则调 coder 产 SELECT

读 ts.json 的 rules，按 `data_flow.schedule_groups` 顺序逐规则调 coder。

**对每个规则**：
```
Task(
  subagent_type="dws-coder",
  description="编码 {rule_code}",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: {rule_code}，产出 SELECT 到 {deliver}/select/。"
)
```

**记住每个 coder 调用返回的 task_id**（规则→会话映射，执行回路要用）。

coder 完成后验证 `{deliver}/select/{rule_code}_select.sql` 已生成。

> coder 内部会：slice_ts 拿切片 → 写 SELECT → check_sql 静态对比 → 落盘。
> 如果 coder 报"静态对比不过"，记录失败规则，继续后面的规则（不阻塞）。

---

## 步骤 6：执行验证（UT，需要数据库）

> 如果没有配置数据库连接（db-sources.json），跳过此步骤，直接到闸口②。

调 run_ut.py 跑执行验证（DDL+INSERT+UT检查）：

```bash
python {scripts}/run_ut.py \
  --ts {deliver}/ts.json \
  --select-dir {deliver}/select \
  --ddl-dir {deliver}/ddl \
  --source {数据源名}
```

将 UT 报告保存到 `{deliver}/_internal/ut_report.txt`。

---

## 步骤 7：执行回路（如有失败）

读 UT 报告，区分失败类型：

**SQL 问题**（字段/类型/语法错误）→ 恢复 coder 会话改：
```
Task(
  subagent_type="dws-coder",
  task_id="{之前记住的 task_id}",   ← 恢复原会话，不重新加载上下文
  description="修复 {rule_code} 执行报错",
  prompt="{rule_code} 执行报错：{报错信息}。请修正 SELECT 后重跑。"
)
```
coder 改完后重跑步骤6验证。**每个规则限 3 轮**。

**环境问题**（权限/连接/源表不存在）→ 不回调 coder，闸口②报告给人。

---

## 步骤 8：闸口②（人确认编码质量）

> **非交互模式**：跳过闸口，打印摘要后结束。

**交互模式**：用 question 展示结果摘要：

```
## 编码完成，请确认

### UT 结果
- ✅ 通过: {N} 个规则
- ❌ 失败: {M} 个规则（如果有）

### 产出文件
- ts.json / ts.md（设计制品）
- select/*.sql（编码制品）
- ddl/*.sql（建表脚本）

请选择：
- ✅ 确认，流程完成
- ✏️ 需要修改
- ❌ 放弃
```

---

# 硬性规则

- ✅ 预处理由你（primary agent）执行，不是 designer 的活
- ✅ 设计段和编码段是一连贯流程，闸口①确认后自动进编码段
- ✅ 按 schedule_groups 顺序逐规则调 coder
- ✅ 记住每个 coder 的 task_id（执行回路用 task_id 恢复会话）
- ✅ DDL/UT 由脚本执行，不让 coder 碰
- ✅ SQL 问题限 3 轮重试，超过闸口报告
- ✅ 环境问题（权限/连接）不回调 coder，直接报告
- ❌ 未经用户确认就结束流程
- ✅ 全程中文
