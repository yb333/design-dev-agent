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
        ├── rs_input.json                 ← 预处理产出（双块：field_mappings 给脚本 + compact 给 designer）
        ├── design_decisions.yaml         ← 设计决策
        ├── ut_precheck_result.json       ← UT 预检结果（步骤6a 产，6b 读）
        ├── ut_report.txt                 ← UT 执行报告（如有数据库）
        └── diagnose/                     ← 数据质量诊断的临时产物（步骤7b 产）
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
  prompt="读取 {deliver}/_internal/rs_input.json 的 compact 块（分块紧凑视图），产出 TS 制品包（ts.json + ts.md）到 {deliver}/。"
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
  --result {deliver}/_internal/ut_precheck_result.json
```

**读预检结果**：全通过 → 继续 6b；有失败 → 走步骤7 分流（SQL 问题回 coder / 环境问题报告人）。

### 步骤 6b：UT 执行（慢，分钟级）

按 load_mode 预处理 + INSERT 灌数据 + UT 检查 + 出报告。

```bash
python CODING_SCRIPTS/ut_execute.py \
  --ts {deliver}/ts.json \
  --select-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --precheck-result {deliver}/_internal/ut_precheck_result.json \
  --report {deliver}/ut_report.md
```

> ⚠️ `--precheck-result` 路径与 6a 的 `--result` 一致（都在 `_internal/` 下）。读不到直接退出（避免预检未通过误灌数据）。
> **超时**：预检/执行都可能跑数分钟，调脚本设 timeout=600000ms。数据库端 statement_timeout（默认600秒）会自动 cancel 超时查询，不留僵尸进程。

---

## 步骤 7：执行回路（如有失败）

读 UT 报告，**按失败项类型分流**：

> ⚠️ 数据质量类失败（主键重复/空值/行数异常）一律**不回 coder**——coder 会用 ROW_NUMBER 去"消除症状"掩盖根因（关联发散）。这类根因在设计层，退回 designer。

**7a. SQL 问题 → coder**（INSERT 报错含 COLUMN/TYPE/SYNTAX/DOES NOT EXIST，或预检 FAIL）。
恢复该规则 coder 旧会话（task_id 在步骤5记的映射里）：
```
Task(subagent_type="dws-coder", task_id="{该规则 task_id}",
     description="修复 {rule_code} SQL 报错",
     prompt="{rule_code} 执行报错：{报错信息}。请修正 SELECT。")
```
改完重跑步骤6。**每规则限 3 轮**。

**7b. 数据质量问题 → designer → 闸口① → coder**。
INSERT 成功但 UT 检查 FAIL（主键重复/空值/行数异常，报告带样例数据）。

① 组**精简依据包**传给 designer（怎么判断是 designer 的角色能力，见 designer.md）：
```
Task(subagent_type="dws-designer", task_id="{designer 的 task_id}",
     description="诊断 {rule_code} 数据质量问题",
     prompt="{rule_code}（{target}）UT 失败：{失败项+样例，摘 UT 报告}\n
              coder 的 SELECT: {deliver}/etl/{rule}.sql\n
              你当初的 join_safety: {摘 ts.json 该规则}\n
              你当初的 business_key: {摘 ts.json}\n
              判断是改设计 / 标需业务确认 / 还是 coder 没按 join_safety 写。")
```
② designer 改完后**必须回闸口①**（question 展示改了哪些 joins/join_safety/business_key + 原因，人确认）——**不能跳过直接让 coder 改**。
③ 闸口①确认后，恢复该规则 coder 旧会话按新设计改 SELECT，改完重跑步骤6。每规则限 3 轮。

> designer/coder 产出的临时分析脚本统一放 `{deliver}/_internal/diagnose/`。

**7c. 环境问题 → 人**（连接/权限/源表不存在/超时）。闸口②报告给人，不回调 agent。

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

**交互模式**：用 question 展示结果摘要（UT 通过/失败数 + 产出文件清单见顶部目录结构），请用户确认 / 修改 / 放弃。

---

# 硬性规则

- 闸口①确认后**自动进编码段**（设计→编码是一连贯流程，中间不交接）
- 记住每个 coder 的 task_id（步骤7 执行回路靠 task_id 恢复会话，不新开）
- **未经用户确认不结束流程**；全程中文
