---
description: DWS ETL 编码流程（生成SELECT→执行验证→闸口②确认）
agent: build
---

你是编码流程的执行者。设计段已完成（ts.json 已产出并经闸口①确认），现在执行编码段。
按以下步骤执行。

用户输入：$ARGUMENTS（资产名或 ts.json 路径）

---

## 产出目录

延续设计段的目录结构，编码产出也放在 `10_project_deliver/{资产名}/ddlc_design_dev/` 下：

```
ddlc_design_dev/
├── ts.json                 ← 设计段产出（编码的输入）
├── select/                 ← 编码段产出（coder 产的 SELECT）
│   └── R0001_select.sql
├── ddl/                    ← 编码段产出（脚本生成的 DDL）
│   └── create_table_xxx.sql
└── _internal/              ← 过程产物
    └── ut_report.txt       ← UT 执行报告
```

> 下文用 `{deliver}` 代指 `10_project_deliver/{资产名}/ddlc_design_dev`。
> 脚本路径用 glob 找：`glob: **/dws-coding/references/run_ut.py`。

---

## 步骤 1：生成 SELECT（逐规则调 coder）

读 ts.json 的 rules，按 `data_flow.schedule_groups` 顺序逐规则调 coder。

**对每个规则**：
```
Task(
  subagent_type="dws-coder",
  description="编码 R0001",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: R0001，产出 SELECT 到 {deliver}/select/。"
)
```

**记住每个 coder 调用返回的 task_id**（规则→会话映射，执行回路要用）。

coder 完成后用 `ls` 验证 `{deliver}/select/` 下已生成 `{rule_code}_select.sql`。

> coder 内部会：slice_ts 拿切片 → 写 SELECT → check_sql 静态对比 → 落盘。
> 如果 coder 报"静态对比不过，3轮没改好"，记录失败规则，继续后面的规则（不阻塞）。

---

## 步骤 2：生成 DDL

所有规则的 SELECT 生成完后，调脚本生成 DDL：

```bash
python {scripts}/assemble_ddl.py --ts {deliver}/ts.json --outdir {deliver}/ddl
```

验证 `{deliver}/ddl/` 下生成了 CREATE TABLE / CREATE VIEW 文件。

---

## 步骤 3：执行验证（UT）

调 run_ut.py 跑执行验证（DDL+INSERT+UT检查）：

```bash
python {scripts}/run_ut.py \
  --ts {deliver}/ts.json \
  --select-dir {deliver}/select \
  --ddl-dir {deliver}/ddl \
  --source {数据源名}
```

> 数据源名从 db-sources.json 配置里取（多 schema 多账号）。
> run_ut.py 会：执行 DDL 建表 → 包装 INSERT 执行 → 跑 UT 检查（主键唯一/非空/行数）→ 输出报告。

**将 UT 报告保存到** `{deliver}/_internal/ut_report.txt`。

---

## 步骤 4：执行回路（如有失败）

读 UT 报告，区分失败类型：

**SQL 问题**（字段/类型/语法错误）→ 恢复 coder 会话改：
```
Task(
  subagent_type="dws-coder",
  task_id="{之前记住的 task_id}",   ← 恢复原会话，不重新加载上下文
  description="修复 R0001 执行报错",
  prompt="R0001 执行报错：{报错信息}。请修正 SELECT 后重跑。"
)
```
coder 改完后重跑步骤3验证。**每个规则限 3 轮**。

**环境问题**（权限/连接/源表不存在）→ 不回调 coder，闸口②报告给人。

**全部通过** → 进闸口②。

---

## 步骤 5：闸口②（人确认编码质量）

**必须暂停等用户确认**。用 question 展示 UT 结果摘要：

```
## 编码完成，请确认

### UT 结果
- ✅ 通过: {N} 个规则
- ❌ 失败: {M} 个规则（如果有）

### 规则明细
{每个规则的 SELECT 字段数 + UT 结果}

### 问题清单（如有）
{失败规则的报错信息}

请选择：
- ✅ 确认编码，交付 SIT
- ✏️ 需要修改（说明哪里要改）
- ❌ 放弃
```

**用户确认** → "编码完成，SQL 制品已就绪于 {deliver}/"。
**用户要改** → 按用户指示修（回 coder 或调脚本）。
**用户放弃** → 结束。

---

# 硬性规则

- ✅ 按 schedule_groups 顺序逐规则调 coder（前序完成才调后续）
- ✅ 记住每个 coder 的 task_id（执行回路用 task_id 恢复会话）
- ✅ DDL/UT 由脚本执行，不让 coder 碰
- ✅ SQL 问题限 3 轮重试，超过闸口报告
- ✅ 环境问题（权限/连接）不回调 coder，直接报告
- ❌ 未经用户确认就交付 SIT
- ✅ 全程中文
