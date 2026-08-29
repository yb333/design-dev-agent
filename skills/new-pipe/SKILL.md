---
name: new-pipe
description: >-
  新建交付全流程剧本（dws-engineer 加载执行）：预处理→设计→闸口①→编码→UT→闸口②→制品。
  优化场景不在此（opt-pipe）；单规则设计/编码不在此（designer/coder 的 skill）。
---

# 新建交付全流程剧本（dws-engineer 执行）

> 任务参数（模式/mapping/rs/资产/交互）由 dws-engineer 解析后进入本剧本；红线与编排者铁律见岗位定义（agents/dws-engineer.md），此处不复述。

---

## 步骤 0：环境自检（动任何输入之前，一次）

```bash
python3 {SKILL_BASE}/scripts/check_env.py
```

- exit 1 = 安装/依赖不符（报错带原因）→ 停，报"环境安装滞后，重跑 install.py"，不改环境继续
- 工具面自检（脚本测不了的行为项）：确认 python 可执行、write 可写 `{deliver}`、task 可起子 agent——任一缺失停，报"调用链权限被钳制，按调用契约部署前提放开上游 bash/write/edit/task"

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
    ├── export/                           ← 平台制品包（UT 通过后生成）
    │   ├── shujia_{表名}.xlsx            ← 术加执行平台导入（10 sheet）
    │   └── lts_{表名}.xlsx               ← LTS 调度平台导入（3 sheet）
    └── _internal/                        ← 过程产物
        ├── rs_input.json                 ← 预处理产出（完整，给脚本读）
        ├── rs_input_view.json            ← 预处理产出（紧凑视图，给 designer 读）
        ├── schema_cache.json             ← 表结构缓存（precheck 连库刷，类型对账用）
        ├── type_risk_decision.yaml       ← 字段类型风险决策（precheck 检出时生成）
        ├── join_type_decision.yaml       ← 关联键类型决策（precheck 检出跨大类时生成）
        ├── design_decisions.yaml         ← 设计决策
        ├── ut_precheck_result.json       ← UT 预检结果（步骤5a 产，5b 读）
        ├── ut_report.txt                 ← UT 执行报告（如有数据库）
        └── diagnose/                     ← 数据质量诊断的临时产物（步骤6b 产）
```

> 下文用 `{deliver}` 代指 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev`。
> **资产名/schema/appid 全从输入推导**（preprocess --probe，见下节）——调用方不传，双源即漂移。

### 脚本路径定位

脚本按**调用方**分布在三个 skill 目录：
- `design-dev-shared/scripts`（SHARED_SCRIPTS）：pipe 编排调的管线脚本（preprocess/precheck/gate_summary/assemble_ddl/assemble_export/ut_precheck/ut_execute/check_db/dispatch_plan/resolve_appid）+ 公共库（dws_db/config_paths/run_ut/ut_diagnose/type_compat/sql_parse/dws_standards/schema_query——后者是字段查询**能力层**，designer 入口 check_field / coder 入口 pick_fields 的内核）。
- `dws-design/scripts`（DESIGN_SCRIPTS）：designer 调的（assemble_ts/explore/fill_type_risk_decision）。
- `dws-coding/scripts`（CODING_SCRIPTS）：coder 调的（slice_ts/check_sql/pick_fields）。

**先定位路径再开工**——本 skill 加载注入的 Base directory 即锚点（`{SKILL_BASE}` = .../skills/new-pipe）。推算脚本目录：

- `SHARED_SCRIPTS` = `{SKILL_BASE}/../design-dev-shared/scripts`（管线脚本 + 公共库）
- `DESIGN_SCRIPTS` = `{SKILL_BASE}/../dws-design/scripts`
- `CODING_SCRIPTS` = `{SKILL_BASE}/../dws-coding/scripts`

bash 调用时用推算出的**绝对路径**（会话 cwd 不在 skill 目录，裸相对路径会指错）。

下文用 `DESIGN_SCRIPTS` 代指设计段脚本目录，`CODING_SCRIPTS` 代指编码段脚本目录，`SHARED_SCRIPTS` 代指公共脚本目录（pipe 管线脚本 + 公共库所在）。
调用时把变量替换为实际路径，例如：`python <SHARED_SCRIPTS>/preprocess.py ...`

### 确定 {deliver}（probe 先行，资产定位全从输入推导）

**资产名/schema/appid 一律从输入推导（调用方不传——幂等设计，不信任输入）**。步骤 1 之前先探测：

```bash
python SHARED_SCRIPTS/preprocess.py --mapping {mapping路径} --rs {RS路径} --probe
```

输出一行 JSON：`{schema, f_table, asset, appid, deliver_hint}`。`{deliver}` = `10_project_deliver/{appid}/{schema}/{asset}/ddlc_design_dev`（appid 查不到时层为空 warn 不阻断，建议先填 schema_apps.json）。探测与正式预处理幂等（同一输入必同一定位）；probe 结果与后续 preprocess 的 meta 不一致属输入自相矛盾，fail loud 报调用方。

---

# ════════ 设计段 ════════

## 步骤 1：预处理（转换 + 校验，分开执行）

从用户输入识别 mapping 文件（.xlsx）和 RS 文件（.md）。

**步骤 1a：转换**（mapping + RS → rs_input.json）

```bash
python SHARED_SCRIPTS/preprocess.py \
  --mapping {mapping路径} \
  --rs {RS路径} \
  --output {deliver}/_internal/rs_input.json
```

> 产出：`rs_input.json`（完整，给脚本读）+ `rs_input_view.json`（紧凑视图，路径传给 designer）。
> `--rs` 可选：无 RS 时调度/增量/DQ 用默认值兜底，mapping 独立驱动核心链路。

**步骤 1b：校验**（检查 rs_input.json 完整性）

```bash
python SHARED_SCRIPTS/precheck.py \
  --input {deliver}/_internal/rs_input.json \
  --decision {deliver}/_internal/type_risk_decision.yaml
```

**校验返回码**：
- 0（PASS）→ 继续
- 1（WARNING）→ 显示警告，问用户是否继续
- 2（INCOMPLETE）→ 看阻断原因分三种：
  - **普通阻断**（schema/字段缺失等，stdout 不含任何 `_PENDING`）→ 停止，让用户修改**源文件**（mapping.xlsx 或 RS.md）后重新执行 1a+1b
  - **★ 决策类阻断**（stdout 含 `TYPE_RISK_PENDING` 和/或 `JOIN_TYPE_RISK_PENDING`——检测同轮全爆）→ 按下方流程分域提问

> ⚠️ 用户修改的是 mapping.xlsx 或 RS.md（源文件），不是 rs_input.json（产物）。
>
> **提问规则（同域打包、跨域串行、改键剪枝）**：
> 1. 先问**关联键域**（≤4 对时一个 question 打包，逐对一个 question 项）；
> 2. **任一对选"改关联键" → 立即剪枝**：不再问类型域、不填任何值，指引用户修
>    mapping.xlsx 后重跑 1a+1b（输入变了，本轮所有决策作废，precheck 一致性校验
>    会重建骨架重问）；
> 3. 无改关联键才问**类型域**（batch + 逐字段，一个 call 打包）。

### 关联键类型决策流程（stdout 含 JOIN_TYPE_RISK_PENDING 时）

precheck 检出关联键类型跨大类（如字符↔数值），输出 `JOIN_TYPE_RISK_PENDING {JSON}`（含双侧类型 + 键值采样 + decision_file 路径）。**用 question 逐对问**（采样值给用户看——内容能否对上，人一眼判断）：
- `转换`（内容实际兼容，如 '123' 对 123 → designer 在 joins 声明 cast，N_JOIN1 校验兜底）
- `改关联键`（关联字段选错了 → 改 mapping.xlsx 源文件后重跑 1a+1b，precheck 会持续阻断到改完）
- `接受`（业务确认豁免，闸口①可见）

**调脚本填值**（不手写 yaml）：

```bash
python DESIGN_SCRIPTS/fill_join_risk_decision.py \
  --decision {deliver}/_internal/join_type_decision.yaml \
  --pair-decisions 'a.prod_code = b.prod_id=>接受' \
  --reasons 'a.prod_code = b.prod_id=>业务确认就这么关联'
```

（--pair-decisions/--reasons 可重复传多对，分隔符 `=>`。）填完**重跑步骤 1b** → 放行（决策回写 rs_input，designer 紧凑视图可见）。

### 类型风险决策流程（stdout 含 TYPE_RISK_PENDING 时）

precheck 检测到"直接复制"字段有源→目标类型转换风险时阻断，输出 `TYPE_RISK_PENDING {JSON}` 摘要行（含 batch 常规风险字段 + individual 跨大类/字符语义差异风险字段 + decision_file 路径）。

**用 question 收集决策**（不让用户手填 YAML），两类分别问：
- **batch（常规风险：长度超长/精度收窄）**：一问定策略。选项 `加安全处理`（ETL 截取/转换保不出错）/ `不加`（接受风险，数据问题以报错暴露）。
- **individual（跨大类不兼容/字符语义差异）**：**按类型对归并提问**——同 源类型→目标类型 的字段合并为一问（同类字段处置几乎总相同），问题文案给字段数+类型对。选项 `全部转换`（ETL SELECT 加 TO_DATE/TO_CHAR/CAST）/ `全部不加`（接受风险）/ `全部返源端`（源端改类型更合适，追问原因）/ `拆开逐个定`（选它再逐字段问）。单次 question ≤4 问，组多分多轮。示例：
  ```
  question("检出 12 个 varchar→numeric 跨大类字段（amount_str、qty_txt 等）怎么处理？",
           options=["全部转换（ETL 加 CAST）", "全部不加（接受风险）", "全部返源端", "拆开逐个定"])
  ```
  按脚本输出的分组问，不自行增删判定项。

> ★ **所有处置都是改 ETL（SELECT 加转换），DDL 目标类型一律不变**——不要理解为改 DDL 的目标类型。
> 决策通过后 precheck 自动回写 rs_input（转换字段改"数据加工"），designer/coder 按加工字段走转换逻辑。

**调脚本填值**（不手写 yaml，避免中文 key/枚举值写错）：

```bash
python DESIGN_SCRIPTS/fill_type_risk_decision.py \
  --decision {deliver}/_internal/type_risk_decision.yaml \
  --batch-strategy "加安全处理" \
  --field-decisions 'biz_date:转换,amount_str:返源端' \
  --reasons 'amount_str:源端建议改decimal类型'
```

参数细节见 `fill_type_risk_decision.py --help`（脚本校验枚举值和字段名，错了 exit 1）。填完**重跑步骤 1b** → 放行继续。

---

## 步骤 2：调 dws-designer 产出 TS

预处理通过后，用 Task 调用 dws-designer。

designer 内部会自行完成"产 design_decisions.yaml → 调 assemble_ts.py 组装 ts.json/ts.md"。

```
Task(
  subagent_type="dws-designer",
  description="产出TS制品包",
  prompt="读取 {deliver}/_internal/rs_input_view.json（分块紧凑视图），产出 TS 制品包（ts.json + ts.md）到 {deliver}/。需要某字段精确细节时再查同目录 rs_input.json。视图中 join_type_risk 段与字段『决策』标记是已人工拍板的输入事实，按其口径设计，不重新质疑方向。"
)
```

designer 完成后用 `ls` 验证 `{deliver}/` 下已生成 ts.json + ts.md。

---

## 步骤 3：闸口①（人确认设计方向）

**这是三条红线之一（语义判断不自主）——必须停下问人，不能自己往下走。**

调脚本从 ts.json 直接生成摘要（不需要 AI 提取）：

```bash
python SHARED_SCRIPTS/gate_summary.py --ts {deliver}/ts.json --rs {deliver}/_internal/rs_input.json

> ★ **表名标准映射（不许以此打回）**：输入资产锚点名是 I 视图（`_i`，对外消费名），
> ts 的物理产出是 F 表（`_f`），I 是 F 的直封镜像视图——`输入 *_i ↔ ts 目标 *_f`
> 是 preprocess 的标准推导（成对产出），不是漂移。闸口①比对表名时按此映射判断。
```

拿到摘要后，**立即调 question 停下等用户确认**（不允许跑完摘要直接进编码段）：

- 用户选"确认设计，进入编码" → 进入步骤 4
- 用户选"需要修改"（说明哪里改）→ 回步骤 2 重新调 designer
- 用户选"放弃" → 结束

> **非交互例外只有一个**：用户/调用方**显式声明**非交互（如 `opencode run` 批量评测）。不得自行判定环境非交互而跳过 question。

---

# ════════ 编码段 ════════

## 步骤 4：编码（闸口①后并行发起）

### 4-0：生成执行计划（先跑，统一判断——不要自己解析 ts.json 猜）

```bash
python SHARED_SCRIPTS/dispatch_plan.py --ts {deliver}/ts.json
```

输出执行计划 JSON：`ddl` / `dq`（含条数）/ `etl_rules` / `init_rules` / `groups` / `summary`。
**发起哪些任务一律以计划为准**——`dq=false` 不发 DQ coder，`init_rules` 空不发 init，`etl_rules` 之外的规则（视图步骤）不调 coder。**先拿完整计划再一次发起。**

闸口①确认后，**4a/4b/4c 互不依赖，在同一消息里并行发起**（4d init 等 4b 完成）。

### 4a：生成 DDL（脚本）

```bash
python SHARED_SCRIPTS/assemble_ddl.py --ts {deliver}/ts.json --outdir {deliver}
```

### 4b：规则 coder（按计划 groups 组内并行）

按执行计划的 `groups` 编排：**组内规则的 coder 在同一消息并行发起（一个消息多个 Task），组间串行（上一组完成再发下一组）**。规则清单以计划 `etl_rules` 为准。

**对每个规则**（★ prompt 只含 ETL 编码任务本身，不提 DDL/DQ/init）：
```
Task(
  subagent_type="dws-coder",
  description="编码 {rule_code}",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: {rule_code}，产出 SELECT 到 {deliver}/etl/。"
)
```

**task_id 由 Task 调用返回后你自己记录**（规则→会话映射，步骤 6 用），**不写进 coder 的 prompt**。完成后验证 `{deliver}/etl/{rule_code}.sql` 已生成。

### 4c：DQ coder（计划 dq=true 时，与 4a/4b 同消息并行）

执行计划 `dq=true`（RS 有 DQ 需求，designer 已翻译；**以计划为准，不自己解析 ts.json**）→ 调 coder 产 DQ（与 4a/4b **同消息**并行发起）：

```
Task(
  subagent_type="dws-coder",
  description="生成DQ检查SQL",
  prompt="DQ 检查 SQL 生成（按 dws-dq skill 流程）：ts.json 路径: {deliver}/ts.json，
          产出检查 SQL 到 {deliver}/dq/。"
)
```

计划 `dq=false` → **跳过**：不调 coder，`dq/` 目录不建。

### 4d：init coder（计划 init_rules 非空时，等 4b 完成）

执行计划 `init_rules` 非空：**4b 所有增量规则 .sql 落盘后**，按 `init_rules` 清单逐个调 coder：

```
Task(
  subagent_type="dws-coder",
  description="编码 {init_rule_code}",
  prompt="ts.json 路径: {deliver}/ts.json，编码规则: {init_rule_code}，产出 SELECT 到 {deliver}/etl/。INIT_ 规则按 SKILL.md §2.5（derive 适配源 SQL 改 filter / explicit 从头写）。"
)
```

计划 `init_rules` 为空（非增量资产）→ 跳过。

**4a/4b/4c/4d 全部完成 → 步骤 5 UT。**

---

## 步骤 5：执行验证（UT，需要数据库）

**不要自己判断有没有数据源**——调脚本检查：

```bash
python SHARED_SCRIPTS/check_db.py --ts {deliver}/ts.json
```

- 如果输出 `DB_OK` → 有数据源，继续跑 UT
- 如果输出 `NO_DB_SOURCE` → 无数据源，跳过 UT，直接到闸口②（告知用户"UT 未执行，需配置 db-sources.json"）

### 步骤 5a：UT 预检（快，秒级）

回退 + DDL + SELECT 预检。不写数据，只验证建表和查询能跑通。

```bash
python SHARED_SCRIPTS/ut_precheck.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --result {deliver}/_internal/ut_precheck_result.json
```

**读预检结果**：全通过 → 继续 5b；有失败 → 走步骤6 分流（SQL 问题回 coder / 环境问题报告人）。

### 步骤 5b：UT 执行（慢，分钟级）

按 load_mode 预处理 + INSERT 灌数据 + UT 检查 + 出报告。

```bash
python SHARED_SCRIPTS/ut_execute.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --precheck-result {deliver}/_internal/ut_precheck_result.json \
  --report {deliver}/ut_report.md
```

> ⚠️ `--precheck-result` 路径与 5a 的 `--result` 一致（都在 `_internal/` 下）。读不到直接退出（避免预检未通过误灌数据）。
> **超时**：预检/执行都可能跑数分钟，调脚本设 timeout=600000ms（数据库端 statement_timeout 自动兜底）。
> ★ **init 资产的 UT 顺序**：有 `init` 段时，ut_precheck/ut_execute 自动**先跑 init 阶段（truncate+全量插建基线），再跑增量阶段（在基线上 merge）**。无需分开调，脚本内部有序两阶段；init 挂了基线就废，后续增量自动跳过。
> ★ **DQ 检查内嵌 5b 尾部**（`ts.dq_rules` 非空且数据完整时自动执行）：0 行=通过，非 0 行=告警。告警/报错阻断出口（exit 1），UT 报告有 DQ 段——分流见步骤 6。

---

## 步骤 6：执行回路（如有失败）

读 UT 报告，**按失败项类型分流**：

> ⚠️ 数据质量类失败（主键重复/空值/行数异常）一律**不回 coder**——coder 会用 ROW_NUMBER 去"消除症状"掩盖根因（关联发散）。这类根因在设计层，退回 designer。

> ⚠️ **类型转换类报错（含 invalid input syntax / operator does not exist）先看报告的"嫌疑报告"段再分流**：有关联键嫌疑（类型跨大类的 JOIN 对）→ 退 designer/人核对关联逻辑，**★禁止用改字段类型来"修复"**（掩盖根因，同 ROW_NUMBER 反模式）；无关联嫌疑才走 6a/6b。

**6a. SQL 问题 → coder**（INSERT 报错含 COLUMN/TYPE/SYNTAX/DOES NOT EXIST，或预检 FAIL；**DQ 段的 FAIL/MISSING 同类**——DQ SQL 执行报错或 dq_{检查类型}.sql 文件缺失）。
恢复该规则 coder 旧会话（task_id 在步骤4b 记的映射里）：
```
Task(subagent_type="dws-coder", task_id="{该规则 task_id}",
     description="修复 {rule_code} SQL 报错",
     prompt="{rule_code} 执行报错：{报错信息}。请修正 SELECT。")
```
改完重跑步骤5。**每规则限 3 轮**。

**6a-DQ. DQ 告警（ALERT，非 0 行）→ 闸口② 人判，不自动改**。UT 报告 DQ 段带违规行样例，人三选一：SQL 方向写反 → 回 coder；阈值/口径不合理 → 回 designer 改 rule_desc（或退 RS 源）；数据真脏 → 人定（接受或退数据侧）。中间阈值的结果依赖数据分布，人工确认预期。

**6b. 数据质量问题 → 人确认根因 → （要改设计才回 designer）→ coder**。
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
> 开发环境数据量/质量与生产不一致，不能仅凭 UT 结果下结论。

② **按人定的根因分流**：
- **源表数据问题** → 不改设计，闸口②报告给人（环境问题归 6c）
- **coder 实现不符** → 恢复 coder 旧会话，指出 SELECT 哪里没按 join_safety 写，改完重跑步骤5
- **关联设计问题 / 业务粒度问题** → 人定具体怎么改（如"JOIN dim_xxx 要加 is_current=1 限定""business_key 补 line_no"），**这时才回 designer 执行修改**：
  ```
  Task(subagent_type="dws-designer", task_id="{designer 的 task_id}",
       description="按确认方案修改 {rule_code}",
       prompt="人已确认根因和方案：{人定的具体改法}\n"
              "请按此方案修改 design_decisions 的 joins/join_safety/business_key，不要自行给其他方案。")
  ```
  designer 改完后**必须回闸口①**（question 展示改了什么 + 人当初定的方案，确认一致）——**不能跳过直接让 coder 改**。

③ 闸口①确认后，恢复该规则 coder 旧会话按新设计改 SELECT，改完重跑步骤5。每规则限 3 轮。

> designer/coder 产出的临时分析脚本统一放 `{deliver}/_internal/diagnose/`。

**6c. 环境问题 → 人**（连接/权限/源表不存在/超时）。闸口②报告给人，不回调 agent。

---

## 步骤 7：生成平台制品包（UT 通过后必跑）

> **前提**：步骤5 UT 全部通过；UT 未执行（无数据库）时，闸口②人工确认通过后再生成。

调 assemble_export.py 生成平台消费的 Excel：

```bash
python SHARED_SCRIPTS/assemble_export.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl/ \
  --outdir {deliver}
```

产出在 `{deliver}/export/` 下：
- `shujia_{表名}.xlsx`（术加执行平台导入，10 sheet）
- `lts_{表名}.xlsx`（LTS 调度平台导入，3 sheet）

> 编码列为占位符（组码 `GR_*`、规则码 ts 码、pv 行 `PV000N`），出厂已做三处闭合校验；子项目中文名留空人填。
> **交付流程（闸口②确认后）**：收集 项目中文名 + 子项目中文名 → 调 `SHARED_SCRIPTS/local/backfill_rule_codes.py`
> 取码替换占位符、按中文名补齐项目/子项目编码及英文名 → 用户拿终版 Excel 直接导入。
> （local/ 是本地扩展目录，脚本按需就位；脚本不存在时跳过此步，告知用户手工处理编码。）

---

## 步骤 8：闸口②（人确认编码质量）

**必须调 question 展示结果摘要等用户确认**（摘要含 UT 通过/失败数 + **DQ 检查结果（0 行=通过；有告警必须列样例与去向判断）** + 产出文件清单），跑完必须停下，不允许自己结束流程：

- 用户选"确认" → 结束流程
- 用户选"修改"（说明哪里改）→ 回对应步骤（编码问题回 coder / 设计问题回 designer）
- 用户选"放弃" → 结束

> 非交互例外同闸口①：仅用户/调用方**显式声明**时跳过。

---

# 硬性规则

- 闸口①确认后**自动进编码段**，中间不交接
- **步骤4 编码段并行发起**：4a/4b/4c 同消息并行（互不依赖），4d 等 4b 增量规则完成
- 记住每个 coder 的 task_id（步骤6 执行回路靠 task_id 恢复会话，不新开）
- **未经用户确认不结束流程**；全程中文
