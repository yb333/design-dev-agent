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
    ├── etl/                              ← 编码产出（coder 产的 SELECT）
    │   └── R0001.sql
    ├── dq/                               ← DQ 检查 SQL（脚本生成）
    ├── ut_report.md                      ← UT 报告（执行验证后生成）
    ├── ddl/                              ← 编码产出（脚本生成的 DDL）
    │   └── create_table_xxx.sql
    ├── export/                           ← 平台制品包（UT 通过后生成，可选）
    │   ├── execution_tasks.xlsx          ← 执行平台导入（10 sheet）
    │   ├── schedule_tasks.xlsx           ← 调度平台导入（3 sheet）
    │   └── export_manifest.json          ← 元数据清单（给内网 skill 读）
    └── _internal/                        ← 过程产物
        ├── rs_input.json                 ← 预处理产出
        ├── design_decisions.yaml         ← 设计决策
        └── ut_report.txt                 ← UT 执行报告（如有数据库）
```

> 下文用 `{deliver}` 代指 `10_project_deliver/{资产名}/ddlc_design_dev`。
> **资产名**从 RS 资产信息或 mapping 目标表推导。

### 脚本路径定位

设计段脚本在 dws-design skill，编码段脚本在 dws-coding skill。
**不要用 glob 找**——直接用 Python 定位全局安装路径（跨平台兼容）：

```bash
python -c "from pathlib import Path; p=Path.home()/'.config'/'opencode'/'skills'/'dws-design'/'scripts'; print(p)"
```

把输出路径记为 `DESIGN_SCRIPTS`（设计段脚本目录），同理获取 `CODING_SCRIPTS`（把 dws-design 换成 dws-coding）。

> 如果全局目录不存在（项目级安装），用当前项目下的 `skills/dws-design/scripts`。

下文用 `DESIGN_SCRIPTS` 代指设计段脚本目录，`CODING_SCRIPTS` 代指编码段脚本目录。
调用时把变量替换为实际路径，例如：`python <DESIGN_SCRIPTS>/preprocess.py ...`

---

# ════════ 设计段 ════════

## 步骤 1：预处理（转换 + 校验，分开执行）

从用户输入识别 mapping 文件（.xlsx）和 RS 文件（.md）。

**步骤 1a：转换**（mapping + RS → rs_input.json）

```bash
python DESIGN_SCRIPTS/preprocess.py \
  --mapping {mapping路径} \
  --rs {RS路径} \
  --output {deliver}/_internal/rs_input.json
```

**步骤 1b：校验**（检查 rs_input.json 完整性）

```bash
python DESIGN_SCRIPTS/precheck.py \
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

**交互模式**：必须暂停等用户确认。

调脚本从 ts.json 直接生成摘要（不需要 AI 提取）：

```bash
python DESIGN_SCRIPTS/gate_summary.py --ts {deliver}/ts.json
```

将脚本输出用 question 展示给用户确认。

**用户确认** → 进入编码段。
**用户要改** → 回步骤 2 重新调 designer。

---

# ════════ 编码段 ════════

## 步骤 4：生成 DDL

调脚本从 ts.json 自动生成 DDL：

```bash
python CODING_SCRIPTS/assemble_ddl.py --ts {deliver}/ts.json --outdir {deliver}
```

> **I 视图自动推导**：mapping 目标表写 `_i` 后缀（如 `dwb_xxx_i`），
> 脚本自动推导出 F 表（`dwb_xxx_f`）并先建 F 表、再建 I 视图。
> 不需要 designer/coder 单独处理 F 表，`_i` 就是完整目标。

---

## 步骤 5：逐规则调 coder 产 SELECT + DQ

读 ts.json 的 rules，按 `data_flow.schedule_groups` 顺序逐规则调 coder。

**对每个规则**（ETL 编码）：
```
Task(
  subagent_type="dws-coder",
  description="编码 {rule_code}",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: {rule_code}，产出 SELECT 到 {deliver}/etl/。"
)
```

**记住每个 coder 调用返回的 task_id**（规则→会话映射，执行回路要用）。

coder 完成后验证 `{deliver}/etl/{rule_code}.sql` 已生成。

> coder 内部会：slice_ts 拿切片 → 写 SELECT → check_sql 静态对比 → 落盘。
> 如果 coder 报"静态对比不过"，记录失败规则，继续后面的规则（不阻塞）。

**DQ 并行生成**（ETL 编码和 DQ 互不依赖，并行调）：

```
Task(
  subagent_type="dws-coder",
  description="生成DQ检查SQL",
  prompt="读取 {deliver}/ts.json 的 dq_rules，为每条 DQ 规则生成检查 SQL，
          产出到 {deliver}/dq/ 目录。
          标准 DQ（主键唯一/审计非空/行数）直接写；
          业务 DQ 按 rule_desc 口径写。
          每个文件命名 dq_{检查类型}.sql。"
)
```

> DQ 不再由脚本生成（assemble_dq 已废弃），全部交给 coder 一次性产出。

---

## 步骤 6：执行验证（UT，需要数据库）

**不要自己判断有没有数据源**——调脚本检查：

```bash
python CODING_SCRIPTS/check_db.py --ts {deliver}/ts.json
```

- 如果输出 `DB_OK` → 有数据源，继续跑 UT
- 如果输出 `NO_DB_SOURCE` → 无数据源，跳过 UT，直接到闸口②（告知用户"UT 未执行，需配置 db-sources.json"）

### 步骤 6a：UT 预检（快，秒级）

回退 + DDL + SELECT 预检。不写数据，只验证建表和查询能跑通。

```bash
python CODING_SCRIPTS/ut_precheck.py \
  --ts {deliver}/ts.json \
  --select-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --result {deliver}/ut_precheck_result.json
```

**读预检结果，判断下一步**：
- 全通过 → 继续步骤 6b
- 有失败 → 看失败原因（DDL/SELECT），区分 SQL 问题/环境问题：
  - **SQL 问题**（字段/类型/语法）→ 回调 coder 改，改完重跑 6a
  - **环境问题**（权限/连接/源表不存在）→ 不回调 coder，闸口②报告给人

### 步骤 6b：UT 执行（慢，分钟级）

按 load_mode 预处理 + INSERT 灌数据 + UT 检查 + 出报告。

```bash
python CODING_SCRIPTS/ut_execute.py \
  --ts {deliver}/ts.json \
  --select-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --report {deliver}/ut_report.md
```

> INSERT 是长耗时操作（大表可能 10-30 分钟）。agent 调脚本后等待返回即可。
> 预检已通过的规则才会执行 INSERT，预检失败的不浪费时间。

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

## 步骤 7.5：生成平台制品包（UT 通过后必跑）

> **前提**：步骤6的 UT 全部通过（SQL 验证稳定后才生成制品包，避免反复改）。
> UT 未执行（无数据库）时，闸口②人工确认通过后再生成。

调 assemble_export.py 生成平台消费的 Excel：

```bash
python CODING_SCRIPTS/assemble_export.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl/ \
  --ddl-dir {deliver}/ddl \
  --outdir {deliver}
```

产出在 `{deliver}/export/` 下：
- `shujia_{表名}.xlsx`（术加执行平台导入，10 sheet）
- `lts_{表名}.xlsx`（LTS 调度平台导入，3 sheet）
- `export_manifest_{表名}.json`（元数据清单）

> ⚠️ 规则编码留空。部署时内网 skill 先获取编码回填 Excel 再导入。
> 后续导入平台是可选的（由内网 skill 执行），但制品包必须生成。

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
- etl/*.sql（编码制品）
- dq/*.sql（DQ 检查脚本）
- ddl/*.sql（建表脚本）
- ut_report.md（UT 报告）
- export/shujia_{表名}.xlsx（术加执行平台制品）
- export/lts_{表名}.xlsx（LTS 调度平台制品）
- export/export_manifest_{表名}.json（元数据清单）

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
