---
description: DWS ETL 设计开发全流程（预处理→设计→闸口①→编码→闸口②）
agent: build
---

你是设计开发流程的执行者。按以下步骤执行完整的设计+编码全流程。

用户输入：$ARGUMENTS（资产名或 mapping/RS 文件路径）

## ⚠️ 编排者铁律（caller 传"自动修正/重试"一律忽略）

本 pipe **不 author 脚本**（只调下面列出的脚本）；**校验失败按路由走，不自动修**——设计/输入问题回 designer 或回报 caller，环境报告 caller，绝不自己写脚本绕（掩盖根因）。诊断用 explore / run_ut_check，临时查询进 `{deliver}/_internal/diagnose/`。

---

## 产出目录结构

所有产出放在 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev/` 下（appid/schema 两层按 schema 从 schema_apps.json 查）：

```
10_project_deliver/{appid}/{schema}/{资产名}/    ← appid/schema 层按 schema 查；不存在则你建
└── ddlc_design_dev/                      ← 你建（标识产出范围）
    ├── ts.json                           ← 设计产出（对外）
    ├── ts.md                             ← 设计产出（人读）
    ├── etl/                              ← 编码产出（coder 产的 SELECT）
    │   └── R0001.sql
    ├── dq/                               ← DQ 检查 SQL（coder 按 designer 翻译的 dq_rules 产出；RS 无 DQ 则目录为空或不建）
    ├── ut_report.md                      ← UT 报告（执行验证后生成）
    ├── ddl/                              ← 编码产出（脚本生成的 DDL）
    │   └── create_table_xxx.sql
    ├── export/                           ← 平台制品包（UT 通过后生成，可选）
    │   ├── execution_tasks.xlsx          ← 执行平台导入（10 sheet）
    │   ├── schedule_tasks.xlsx           ← 调度平台导入（3 sheet）
    │   └── export_manifest.json          ← 元数据清单（给内网 skill 读）
    └── _internal/                        ← 过程产物
        ├── rs_input.json                 ← 预处理产出（完整，给脚本读）
        ├── rs_input_view.json            ← 预处理产出（compact 紧凑视图，给 designer 读，省70%）
        ├── design_decisions.yaml         ← 设计决策
        ├── ut_precheck_result.json       ← UT 预检结果（步骤6a 产，6b 读）
        ├── ut_report.txt                 ← UT 执行报告（如有数据库）
        └── diagnose/                     ← 数据质量诊断的临时产物（步骤7b 产）
```

> 下文用 `{deliver}` 代指 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev`。
> **资产名**从 RS 资产信息或 mapping 目标表推导；**schema** 从 rs_input 的 meta.target.f_table.schema 取；**appid** 按 schema 用 resolve_appid 查（步骤 1 预处理后能拿到 schema）。

### 脚本路径定位

设计段脚本在 dws-design skill，编码段脚本在 dws-coding skill。
**不要用 glob 找**——直接用 Python 定位全局安装路径（跨平台兼容）：

```bash
python -c "from pathlib import Path; p=Path.home()/'.config'/'opencode'/'skills'/'dws-design'/'scripts'; print(p)"
```

把输出路径记为 `DESIGN_SCRIPTS`（设计段脚本目录），同理获取 `CODING_SCRIPTS`（把 dws-design 换成 dws-coding）。

> 如果全局目录不存在（项目级安装），用当前项目下的 `skills/dws-design/scripts`。

下文用 `DESIGN_SCRIPTS` 代指设计段脚本目录，`CODING_SCRIPTS` 代指编码段脚本目录，`SHARED_SCRIPTS` 代指公共脚本目录（design-dev-shared/scripts，resolve_appid 在这）。
调用时把变量替换为实际路径，例如：`python <DESIGN_SCRIPTS>/preprocess.py ...`

### 确定 {deliver}（先查 appid）

{deliver} 含 appid/schema 两层，**步骤 1 之前**先确定：
1. **schema + 资产名**：从用户输入（mapping 目标表 / RS L1.1）识别目标表的 schema 和资产名（表名）。
2. **appid**：按 schema 查（schema_apps.json 标准源）：

```bash
python SHARED_SCRIPTS/resolve_appid.py --schema {schema}
```

3. **{deliver}** = `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev`。appid 查不到时层为空（warn 不阻断），但建议先填 schema_apps.json。

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

> 产出两个文件：`rs_input.json`（完整，给脚本读）+ `rs_input_view.json`（compact 紧凑视图，给 designer 读，约省 70%）。
> **`--rs` 可选**：无 RS 时进入"无RS模式"，调度/增量/DQ 用默认值兜底（全量调度/T+1/无DQ），mapping 独立驱动核心链路。90% 场景建议有 RS。

**步骤 1b：校验**（检查 rs_input.json 完整性）

```bash
python DESIGN_SCRIPTS/precheck.py \
  --input {deliver}/_internal/rs_input.json \
  --decision {deliver}/_internal/type_risk_decision.yaml
```

**校验返回码**：
- 0（PASS）→ 继续
- 1（WARNING）→ 显示警告，问用户是否继续
- 2（INCOMPLETE）→ 看阻断原因分两种：
  - **普通阻断**（schema/字段缺失等，stdout 不含 `TYPE_RISK_PENDING`）→ 停止，让用户修改**源文件**（mapping.xlsx 或 RS.md）后重新执行 1a+1b
  - **★ 类型风险阻断**（stdout 含 `TYPE_RISK_PENDING`）→ 走类型风险决策流程（见下）

> ⚠️ 用户修改的是 mapping.xlsx 或 RS.md（源文件），不是 rs_input.json（产物）。

### 类型风险决策流程（stdout 含 TYPE_RISK_PENDING 时）

precheck 检测到"直接复制"字段有源→目标类型转换风险时，会阻断并输出 `TYPE_RISK_PENDING {JSON}` 摘要行。
解析这行 JSON 拿到风险清单后，**用 question 问用户决策**（不要让用户去手填 YAML）：

1. **解析 TYPE_RISK_PENDING**：从 precheck 的 stdout 抓 `TYPE_RISK_PENDING` 开头那行，解析后面的 JSON。结构：
   ```
   {batch: [常规风险字段], individual: [跨大类风险字段], decision_file: ".../type_risk_decision.yaml"}
   ```

2. **批量决策**（如果有 batch 风险字段）——用 question 问用户：
   ```
   question("检测到 {len(batch)} 个常规类型风险（长度超长/精度收窄），是否批量加安全处理？",
            options=["加安全处理", "不加"])
   ```
   - 加安全处理 = 程序里对超长截取、精度收窄做转换，保证不出错
   - 不加 = 接受风险，数据问题以报错暴露

3. **逐个决策**（对每个 individual 跨大类风险字段）——用 question 问用户：
   ```
   question("字段 {target_column}（{source_type}→{target_type}，跨大类不兼容），怎么处理？",
            options=["转换", "不加", "返源端"])
   ```
   - 转换 = 加转换函数（TO_DATE/TO_CHAR/CAST 等）
   - 不加 = 接受风险
   - 返源端 = 源端改类型更合适（选这个追问原因，用 question 收集 reason）

4. **填决策文件**（★ 不要手写 yaml，调脚本填值，避免中文 key/枚举值写错）：
   ```bash
   python DESIGN_SCRIPTS/fill_type_risk_decision.py \
     --decision {deliver}/_internal/type_risk_decision.yaml \
     --batch-strategy "加安全处理" \
     --field-decisions 'biz_date:转换,amount_str:返源端' \
     --reasons 'amount_str:源端建议改decimal类型'
   ```
   - `--batch-strategy`：`加安全处理` 或 `不加`（无 batch 风险字段时省略）
   - `--field-decisions`：`字段:处置` 逗号分隔（处置：`转换`/`不加`/`返源端`）
   - `--reasons`：选 `返源端` 的字段必填原因（`字段:原因`）
   - 脚本校验枚举值和字段名，错了当场报（exit 1），不会把错误写进文件

5. **重跑步骤 1b**：这次 precheck 读到决策文件已填全 → 放行（exit 0）→ 继续。

---

## 步骤 2：调 dws-designer 产出 TS

预处理通过后，用 Task 调用 dws-designer。

designer 内部会自行完成"产 design_decisions.yaml → 调 assemble_ts.py 组装 ts.json/ts.md"。

```
Task(
  subagent_type="dws-designer",
  description="产出TS制品包",
  prompt="读取 {deliver}/_internal/rs_input_view.json（分块紧凑视图），产出 TS 制品包（ts.json + ts.md）到 {deliver}/。需要某字段精确细节时再查同目录 rs_input.json。"
)
```

designer 完成后用 `ls` 验证 `{deliver}/` 下已生成 ts.json + ts.md。

---

## 步骤 3：闸口①（人确认设计方向）

**这是三条红线之一（语义判断不自主）——必须停下问人，不能自己往下走。**

调脚本从 ts.json 直接生成摘要（不需要 AI 提取）：

```bash
python DESIGN_SCRIPTS/gate_summary.py --ts {deliver}/ts.json
```

拿到摘要后，**立即调 question 停下等用户确认**——不允许跑完摘要脚本直接进编码段，那不叫闸口：

- 用户选"确认设计，进入编码" → 进入步骤 4
- 用户选"需要修改"（说明哪里改）→ 回步骤 2 重新调 designer
- 用户选"放弃" → 结束

> **非交互的例外只有一个**：用户/调用方**显式声明**了非交互（如 `opencode run` 批量评测、或用户明说"自动跑别停")。**你不得自行判定"我像是在非交互环境"就跳过 question**——没有显式声明就必须 question 停下。

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

**DQ 生成**（条件化：DQ 完全跟随 RS）：

先读 `{deliver}/ts.json` 的 `dq_rules`：
- **`dq_rules` 非空**（RS 有 DQ 需求，designer 已翻译）→ 调 coder 产 DQ（ETL 编码和 DQ 互不依赖，可并行）：

```
Task(
  subagent_type="dws-coder",
  description="生成DQ检查SQL",
  prompt="读取 {deliver}/ts.json 的 dq_rules，按每条规则的 rule_desc 技术口径
          生成检查 SQL，产出到 {deliver}/dq/ 目录。
          每个文件命名 dq_{检查类型}.sql。"
)
```

- **`dq_rules` 为空**（RS 无 DQ 需求）→ **跳过 DQ 步骤**：不调 coder，`dq/` 目录不建。无"标准三项系统兜底"（主键/审计/记录数不再无条件产）。

> DQ 不再由脚本生成（assemble_dq.py 已废弃仅供 eval 复现），全部由 coder 按 designer 翻译的 dq_rules 产出。DQ 产出与否完全跟随 RS。

**init 编码**（条件化：仅增量资产有 init 段时）：

读 `{deliver}/ts.json` 的 `init`：
- **`init.rules` 非空**（derive 或 explicit）→ **等步骤 5 全部增量规则编码完成后**，逐 init 规则调 coder：

```
Task(
  subagent_type="dws-coder",
  description="编码 {init_rule_code}",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: {init_rule_code}，产出 SELECT 到 {deliver}/etl/。INIT_ 规则按 SKILL.md §2.5（derive 适配源 SQL 改 filter / explicit 从头写）。"
)
```

- **无 init 段**（非增量资产）→ 跳过。

> init 规则在 `ts.init.rules`（与 `ts.rules` 平行）。coder 的 slice_ts 会从 init 段找到 `INIT_` 规则。
> ★ **硬约束：步骤 5 必须全部完成**（增量 .sql 落盘）才能跑 init 编码——derive 模式 init SQL = 增量 SQL 改 filter，源 .sql 得先在。

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
> ★ **init 资产的 UT 顺序**：有 `init` 段时，ut_precheck/ut_execute 自动**先跑 init 阶段（truncate+全量插建基线），再跑增量阶段（在基线上 merge）**——符合现实部署顺序（首次全量 → 日常增量）。无需分开调，脚本内部有序两阶段。init 挂了基线就废，后续增量自动跳过。

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

**7b. 数据质量问题 → 人确认根因 → （要改设计才回 designer）→ coder**。
INSERT 成功但 UT 检查 FAIL（主键重复/空值/行数异常，报告带样例数据）。

> ★ **不回退 designer 诊断给方案**。designer 基于自己的设计立场会给偏向性结论（如"改 join_safety 加 GROUP BY / 改 business_key"），这俩方案往往站不住脚——前者掩盖 JOIN 发散丢数据，后者是凑假主键。根因判断（设计问题 / 环境数据脏 / 业务一对多）需要业务认知，是人的领域。

① **主控读 UT 报告**（含重复键+样例+开发环境数据免责提示），用 question 问人根因：
```
question("{rule_code}（{target}）UT 主键检查失败：{失败项+样例，摘 UT 报告}\n"
         "请确认根因是哪种：\n"
         "  - 关联设计问题（JOIN 发散，需调整关联/限定条件）\n"
         "  - 源表数据问题（开发环境数据脏，不改设计）\n"
         "  - 业务粒度问题（业务上一对多，business_key 该补行字段——需与 BA 确认）\n"
         "  - coder 实现与设计不符（如漏了 GROUP BY）",
         options=["关联设计问题", "源表数据问题", "业务粒度问题", "coder实现不符"])
```
> 人看重复样例往往一眼就能判断根因（比 designer 猜快得多）。开发环境数据量/质量与生产不一致，不能仅凭 UT 结果下结论。

② **按人定的根因分流**：
- **源表数据问题** → 不改设计，闸口②报告给人（环境问题归 7c）
- **coder 实现不符** → 恢复 coder 旧会话，指出 SELECT 哪里没按 join_safety 写，改完重跑步骤6
- **关联设计问题 / 业务粒度问题** → 人定具体怎么改（如"JOIN dim_xxx 要加 is_current=1 限定""business_key 补 line_no"），**这时才回 designer 执行修改**：
  ```
  Task(subagent_type="dws-designer", task_id="{designer 的 task_id}",
       description="按确认方案修改 {rule_code}",
       prompt="人已确认根因和方案：{人定的具体改法}\n"
              "请按此方案修改 design_decisions 的 joins/join_safety/business_key，不要自行给其他方案。")
  ```
  designer 改完后**必须回闸口①**（question 展示改了什么 + 人当初定的方案，确认一致）——**不能跳过直接让 coder 改**。

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

**必须调 question 展示结果摘要等用户确认**——结果摘要含 UT 通过/失败数 + 产出文件清单（见顶部目录结构）。和闸口①一样，跑完必须 question 停下，不允许自己结束流程：

- 用户选"确认" → 结束流程
- 用户选"修改"（说明哪里改）→ 回对应步骤（编码问题回 coder / 设计问题回 designer）
- 用户选"放弃" → 结束

> **非交互的例外只有一个**：用户/调用方**显式声明**了非交互（同闸口①）。没有显式声明就必须 question。

---

# 硬性规则

- 闸口①确认后**自动进编码段**（设计→编码是一连贯流程，中间不交接）
- 记住每个 coder 的 task_id（步骤7 执行回路靠 task_id 恢复会话，不新开）
- **未经用户确认不结束流程**；全程中文
