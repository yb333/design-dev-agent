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
python {SKILL_BASE}/scripts/check_env.py
```

- exit 1 = 环境/依赖不符（报错带原因与修复指引：项目仓部署=更新仓，全局安装=重跑 install.py）→ 停，不改环境继续
- 工具面自检（脚本测不了的行为项）：确认 python 可执行、write 可写 `{deliver}`、task 可起子 agent——任一缺失停，报"调用链权限被钳制，按调用契约部署前提放开上游 bash/write/edit/task"

---

## 产出目录结构

所有产出放在 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev/` 下（appid/schema 两层按 schema 从 schema_apps.json 查）：

```
10_project_deliver/{appid}/{schema}/{资产名}/    ← appid/schema 层按 schema 查；不存在则你建
└── ddlc_design_dev/build/                 ← 你建（增量现场=产出范围）
        ├── ts.json                       ← 主线设计产出（无 DQ；闸口①确认后冻结）
    ├── {资产名}_ts.md                     ← 设计文档（主线章节+DQ 章节追加渲染；产出标准带 f_table 短名前缀）
    ├── dq.json                           ← DQ 元数据唯一源（producer 产出经 assemble_dq 装配；无 DQ 需求则无此文件）
    ├── etl/                              ← 编码产出（coder 产的 SELECT）
    │   └── R0001.sql
    ├── dq/                               ← DQ 检查 SQL（dws-dq-producer 独立设计实现；RS 无 DQ 则目录为空或不建）
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

> 下文用 `{deliver}` 代指 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev/build`——
> **增量现场**（目录模型 2026-09-07 终态：新建=特殊优化场景，其增量恰好是全部产出——
> 与 opt 场景的 build/ 同一目录同一语义）。流程中一切产出在 build/ 下（位置不漂移，
> 闸口②确认后 adopt 提取本源件生成 `{ddlc}/archive/` 档案；剩余留 build 待下次清场）。
> **资产名/schema/appid 全从输入推导**（preprocess --probe，见下节）——调用方不传，双源即漂移。

### 脚本路径定位

脚本按**消费单元**分布（单元=拥有自己 scripts 目录的 skill，薄指针 skill 不算单元；被 ≥2 个目录单元复用 → shared，单一单元 → 自己的 scripts——章程见 AGENTS 编码约定）：
- **本剧本 `scripts/`（PIPE_SCRIPTS = `{SKILL_BASE}/scripts`）**：new-pipe 专属管线脚本（precheck/gate_summary/dispatch_plan/assemble_export/ut_precheck/ut_execute/ut_diagnose + check_env 步骤0 探针（fill_type_risk/fill_join_risk 已下沉 shared，两 pipe 共用））。
- `design-dev-shared/scripts`（SHARED_SCRIPTS = `{SKILL_BASE}/../design-dev-shared/scripts`）：**共用入口**（preprocess——两剧本共用 / check_db——两剧本共用 / assemble_ddl——new-pipe 直调+opt 侧 assemble_ddl_opt import / resolve_appid）+ **公共库**（dws_db/config_paths/run_ut/sql_parse/dws_standards/ts_compat/type_compat/schema_query——schema_query 是字段查询能力层，designer 入口 check_field / coder 入口 pick_fields 的内核）。
- `dws-design/scripts`（DESIGN_SCRIPTS = `{SKILL_BASE}/../dws-design/scripts`）：designer 调的（assemble_ts/explore/check_field/pick_targets/fill_*_decision）。
- `dws-coding/scripts`（CODING_SCRIPTS = `{SKILL_BASE}/../dws-coding/scripts`）：coder 调的（slice_ts/check_sql/pick_fields）。
- `dws-dq/scripts`（DQ_SCRIPTS = `{SKILL_BASE}/../dws-dq/scripts`）：DQ producer 写完即跑的 assemble_dq（校验装配渲染，2026-09-21 归位自 new-pipe——producer 岗位工具对齐 pick_dq_context 先例）。

**先定位路径再开工**——本 skill 加载注入的 Base directory 即锚点（`{SKILL_BASE}` = .../skills/new-pipe）。

bash 调用时用推算出的**绝对路径**（会话 cwd 不在 skill 目录，裸相对路径会指错）。

下文用 `PIPE_SCRIPTS` 代指本剧本脚本目录，`DESIGN_SCRIPTS`/`CODING_SCRIPTS`/`DQ_SCRIPTS` 代指设计/编码/DQ 段脚本目录，`SHARED_SCRIPTS` 代指 shared 公共目录（共用入口 + 公共库）。
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
python PIPE_SCRIPTS/precheck.py \
  --input {deliver}/_internal/rs_input.json \
  --decision {deliver}/_internal/type_risk_decision.yaml
```

**校验返回码**：
- 0（PASS）→ 继续
- 1（WARNING）→ 展示警告文本后**直接继续**（警告是信息性告知非决策项——有默认行为、随流程汇进闸口①材料；交互模式展示给人知情，不问不停。真正要人定的在 exit 2 的决策类阻断里）
- 2（INCOMPLETE）→ 看阻断原因分三种：
  - **普通阻断**（schema/字段缺失等，stdout 不含任何 `_PENDING`）→ 停止，让用户修改**源文件**（mapping.xlsx 或 RS.md）后重新执行 1a+1b。**例外：值域溢出类 error**（`[值域溢出·模型问题]`）不是纯改源文件问题——按下方「值域溢出处理菜单」分角色二选一
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
python SHARED_SCRIPTS/fill_join_risk_decision.py \
  --decision {deliver}/_internal/join_type_decision.yaml \
  --pair-decisions 'a.prod_code = b.prod_id=>接受' \
  --reasons 'a.prod_code = b.prod_id=>业务确认就这么关联'
```

（--pair-decisions/--reasons 可重复传多对，分隔符 `=>`。）填完**重跑步骤 1b** → 放行（决策回写 rs_input，designer 紧凑视图可见）。

### 类型风险决策流程（stdout 含 TYPE_RISK_PENDING 时）

precheck 检测到"直接复制"字段有源→目标类型转换风险时阻断，输出 `TYPE_RISK_PENDING {JSON}` 摘要行（含 batch 常规风险字段 + individual 跨大类/字符语义差异风险字段 + decision_file 路径）。

**用 question 收集决策**（不让用户手填 YAML），两类分别问：
- **batch（常规风险：长度超长/精度收窄）**：一问定策略。选项 `加安全处理`（守卫式转换：非法值置 NULL 被 DQ 抓；**字符收窄=按目标类型长度语义截取**（DWS 官方：varchar/varchar2=字节 SUBSTRB / nvarchar 系=字符 SUBSTR——表达式写死唯一源 type_compat.char_trunc_expr），尾部丢失闸口①披露——**不覆盖数值整数位溢出**，另见值域 error）/ `不加`（接受风险，数据问题以报错暴露）。
- **individual（跨大类不兼容/字符语义差异）**：**按类型对归并提问**——同 源类型→目标类型 的字段合并为一问（同类字段处置几乎总相同），问题文案给字段数+类型对。选项 `全部转换`（ETL SELECT 加 TO_DATE/TO_CHAR/CAST）/ `全部不加`（接受风险）/ `全部返源端`（源端改类型更合适，追问原因；**本轮终止**，修正输入后重跑）/ `拆开逐个定`（选它再逐字段问）。单次 question ≤4 问，组多分多轮。示例：
  ```
  question("检出 12 个 varchar→numeric 跨大类字段（amount_str、qty_txt 等）怎么处理？",
           options=["全部转换（ETL 加 CAST）", "全部不加（接受风险）", "全部返源端", "拆开逐个定"])
  ```
  按脚本输出的分组问，不自行增删判定项。

> ★ **所有处置都是改 ETL（SELECT 加转换），DDL 目标类型一律不变**——不要理解为改 DDL 的目标类型。
> 决策通过后 precheck 自动回写 rs_input（转换字段改"数据加工"），designer/coder 按加工字段走转换逻辑。

**调脚本填值**（不手写 yaml，避免中文 key/枚举值写错）：

```bash
python SHARED_SCRIPTS/fill_type_risk_decision.py \
  --decision {deliver}/_internal/type_risk_decision.yaml \
  --batch-strategy "加安全处理" \
  --field-decisions 'biz_date:转换,amount_str:返源端' \
  --reasons 'amount_str:源端建议改decimal类型'
```

参数细节见 `fill_type_risk_decision.py --help`（脚本校验枚举值和字段名，错了 exit 1）。填完**重跑步骤 1b** → 放行继续。

### 值域溢出处理菜单（预检 `[值域溢出·模型问题]` error / UT `numeric field overflow`·`value too long` 共用）

目标定义装不下源数据（整数位溢出——与类型风险决策无关，"加安全处理"对它无效）。**分角色二选一**：

1. **源输入问题 → BA**：改 mapping 目标类型/长度，重跑 1a+1b（确定性解法，默认推荐）；
2. **设计/实现决策 → SE 拍板**：显式拍板置空/截断（不改业务需求，静默丢数据须明知）→ designer 写显式口径（N35 语义）→ coder 实现。

> 角色边界：源输入问题（mapping/RS 内容错或定窄）归 **BA**；过程中需要拍板的设计/实现决策（不动业务需求，如置空/截断取舍）归 **SE**（人）。无论哪条都**禁回 coder**——coder 对这类问题只会打"超长置空/截断"补丁，静默丢数据掩埋根因（ROW_NUMBER 反模式同族）。

---

## 步骤 2：调 dws-designer 产出 TS

预处理通过后，用 Task 调用 dws-designer。

designer 内部会自行完成"产 design_decisions.yaml → 调 assemble_ts.py 组装 ts.json + {资产名}_ts.md"。

```
Task(
  subagent_type="dws-designer",
  description="设计（评估+TS）",
  prompt="先做输入评估（view 的「评估清单」段→填空→一次 explore --eval）。完成判据双态：评估有疑点→回复=评估结果+疑点清单（各补一句疑似方向）并结束本轮——这是本任务的合格完成形态（你会被带答案恢复继续；先想后续设计没有价值：答案若改输入，设计全部作废）；评估无疑点→继续五层设计，产出 TS 制品包（ts.json + {资产名}_ts.md）到 {deliver}/。输入只读 {deliver}/_internal/rs_input_view.json（紧凑视图，唯一人读入口——rs_input.json 是脚本域文件不读）。视图**若含** join_type_risk 段或字段『决策』标记（1b 有人工决策时才有——没有则忽略本句），它是已拍板的输入事实，按其口径设计不重新质疑方向。"
)
```

**记录 Task 返回的 task_id**——designer 会话恢复（上报后带答案续跑）= 再发 Task 同 subagent_type + 同 task_id，会话带全部前文继续。

designer 完成后用 `ls` 验证 `{deliver}/` 下已生成 ts.json 与 `{资产名}_ts.md`（产出命名标准：md 带 f_table 短名前缀）。

**上报处理=第一响应人协议**（方法手册 `references/report-triage.md`，四步核实→诊断→影响→路由，**永不裸转发**）。评估层上报（回复=评估结果[join_safety 事实行+疑点清单]+⚠ 阻塞首行）是**预期产物不是异常**——处理回路：

1. **疑点分型**（手册有表）：①声明缺失②声明不符③a 从表键发散[--edge 适用] / ③b 主表粒度线发散[无边可试算——材料直接带选项：补键/退BA] ④口径不全⑤`?` 未答；
2. **做实**（R1 套路封顶 2 步）：⑤查 mapping——答案在既有材料里=**自答**，Task 带 task_id 恢复 designer 会话续跑（不问人）；①②查证原文把差异摆清；④不可验，直接进材料；③**必跑边级试算**（人拿"当前不膨胀但未来命中即膨胀"和拿"可能发散"是完全不同的决策；**无试算结论进问人材料=裸转发**）——**无需 --ts**（评估期 ts 未产正用此模式；--rule/--all 是有 ts 后 UT/闸口① 的用法）：

```
python {skill目录}/scripts/diagnose_fanout.py --rs {deliver}/_internal/rs_input.json --edge
```

   **零参数直接跑**：自动试算落盘里全部"从表键不唯一"疑点（逐边结论+◆分隔+合并落盘）——疑点清单 designer `--eval` 已落盘 `eval_result.json`，表/键/限定/对侧全部自动派生（对侧键=关联条件配对列，复合度天然一致；自然语言边兜底主表推断+披露）。单疑点复测才用 `--doubt {别名}`（链式边加 `--partner`）；主表粒度线疑点（③b）会被工具拒绝并指路——不跑试算，材料直接带选项。参数手传兜底：`--override --join-key-b/--where-b ...`（走同一存在性闸）。
3. **攒批问人一次**（四件套：实测事实/根因方向/影响[边试算结论]/选项——**选择题形态**，人只选编号、reason 由 engineer 标准化代笔；人写自由文本=按内容自由决策不硬套模板）——疑点全列齐，不逐条拉扯；
4. **按答案路由**：修源端（退 BA——修数据/修口径/定收敛口径，收敛决策归源端我们只做技术实现） → 终止本轮（输出终止报告：上报事实+人的选择+重启条件[源端修正后重跑步骤 1]，评估层设计作废是预期内）｜采纳已声明条件（mapping 声明过限定、设计漏采纳——试算验证有效后补进 join） → 带**裁决**恢复 designer 会话（只带裁决不带试算分析）｜知情接受（试算证明当前不影响主表粒度，零改动） → 带裁决恢复（designer 落 join_safety 该关联 `unique=false + reason="试算不影响主表粒度，人判知情接受"`——闸口① diagnose --all 已知接受不重复弹，档案留痕）｜自由文本 → 按内容自由决策。

★ **上报中已含"人已拍板"的决策（此前任一环节问过、答案随上报带回）→ 直接按其执行，不再发起确认**——终止报告写清决策链（何时问的、人答的什么）供回溯。一次决策只问一次。

---

## 步骤 3：闸口①（人确认设计方向）

**这是三条红线之一（语义判断不自主）——必须停下问人，不能自己往下走。**

调脚本从 ts.json 直接生成摘要（不需要 AI 提取）：

```bash
python PIPE_SCRIPTS/gate_summary.py --ts {deliver}/ts.json --rs {deliver}/_internal/rs_input.json

> ★ **表名标准映射（不许以此打回）**：输入资产锚点名是 I 视图（`_i`，对外消费名），
> ts 的物理产出是 F 表（`_f`），I 是 F 的直封镜像视图——`输入 *_i ↔ ts 目标 *_f`
> 是 preprocess 的标准推导（成对产出），不是漂移。闸口①比对表名时按此映射判断。
```

拿到摘要后，**先跑关联质量批量预检**（结论进闸口材料，**披露不阻断**——嫌疑可能是开发库数据脏，人判；exit 2=无库跳过不拦闸口）：

```bash
python PIPE_SCRIPTS/diagnose_fanout.py --ts {deliver}/ts.json --all
```

然后**立即调 question 停下等用户确认**（不允许跑完直接进编码段）。**DQ 不门闸口①**（2026-09-15 复调：方案 V 曾把 DQ 前移塞人审窗口致闸口①被 DQ 完成时间门住[+20min]——DQ 修复成本分钟级不值得最贵的审前位；DQ 设计材料归闸口②与执行结果同屏）。**question 模板分场景**：

**检查全部通过**（三常规选项）：

```
question("闸口①设计确认（{资产}）：{gate_summary 摘要——表/规则数/字段数}\\n"
         "关联质量：全部通过。请选择：",
         options=["确认设计，进入编码",
                  "需要修改设计（说明哪里改→回 designer；涉 DQ 字段则连带 DQ 重做）",
                  "放弃"])
```

**检出问题**（不唯一/矛盾信号/丢行——追加退 BA 选项，发散类现实大概率选它）：

```
question("闸口①设计确认（{资产}）：{gate_summary 摘要}\\n"
         "关联质量：{diagnose_fanout 结论——✗ 不唯一表+关联条件原文+输入声明对照 / 矛盾信号+条件原文}\\n"
         "请选择：",
         options=["确认设计，进入编码",
                  "需要修改设计（说明哪里改→回 designer）",
                  "源端输入问题→退 BA（修 mapping/源数据后重跑 1a 全流程）",
                  "放弃"])
```

- 用户选"确认设计，进入编码" → 进入步骤 4
- 用户选"需要修改设计"（说明哪里改）→ 回步骤 2 重新调 designer（DQ 尚未起跑——改完结构直接带新 ts 进步骤 4，无联动成本）
- 用户选"源端输入问题→退 BA" → 人协调 BA 修源端（数据一对多/脏/关联声明），修完**重跑 1a 全流程**（输入变更全流程重来——恢复执行规则同款）
- 用户选"放弃" → 结束

> **非交互例外只有一个**：用户/调用方**显式声明**非交互（如 `opencode run` 批量评测、契约参数 `交互: non-interactive`）。不得自行判定环境非交互而跳过 question。
> 非交互只豁免**流程闸口**（①②不等待、产物人后审）；**人工决策项不豁免**——类型风险决策（1b）/关联键决策（1b）/UT 数据质量根因（6b）照常 fail loud 停下上报待决（无安全默认，不代答不选默认）。

---

# ════════ 编码段 ════════

## 步骤 4：编码（闸口①后并行发起）

### 4-0：生成执行计划（先跑，统一判断——不要自己解析 ts.json 猜）

```bash
python PIPE_SCRIPTS/dispatch_plan.py --ts {deliver}/ts.json
```

输出执行计划 JSON：`ddl` / `etl_rules` / `init_rules` / `groups` / `dq` / `summary`。
**发起哪些任务一律以计划为准**——`init_rules` 空不发 init，`etl_rules` 之外的规则（视图步骤）不调 coder，`dq.required=true` 才起 4c（false=显式跳过——计划里明示，不是漏了）。**先拿完整计划再一次发起。**

闸口①确认后，**4a/4b/4c 互不依赖，在同一消息里并行发起**（4d init 等 4b 完成）。DQ 走 4c 与 coder 并行——谁慢等谁，DQ 时间被 coder 链吸收（2026-09-15 复调：此前方案 V 前移 DQ 塞闸口①窗口，人审快于 DQ 时闸口①被完成时间门住，+20min 实测）。

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

### 4c：DQ producer（与 4a/4b 同消息并行；dq_requirements 非空才起）

**DQ 已拆出主线 designer（2026-09-14）**：独立岗位 dws-dq-producer 一体完成 DQ 翻译/设计与 SQL 实现（断言式翻译 + 对比式独立重算）。`_internal/rs_input.json` 的 `dq_requirements` 非空才起；空则跳过（无 dq.json/ts.md 无 DQ 章节，全程零 DQ）。

```
Task(
  subagent_type="dws-dq-producer",
  description="DQ检查设计实现",
  prompt="DQ 检查的设计与实现（按 dws-dq skill 流程）：rs_input: {deliver}/_internal/rs_input.json，
          ts: {deliver}/ts.json（只读结构），先完成规划（切片 plan 工作单——场景确认/
          融合裁决/declined 确认/rule_id 定号）再写 SQL，产 dq.json 到 {deliver}/、
          检查 SQL 到 {deliver}/dq/（文件名=纯 rule_id，如 DQ_01.sql——零清洗，装饰名由校验器统一 rename）。
          写完即跑 assemble_dq 校验补全（命令见 skill §3），问题一轮修完再重跑，全绿才交卷
          （判非自己写错的契约矛盾→⚠上报，不删条目不删文件；取消检查=declined 申报归人拍板）。"
)
```

**交卷复核（轻量——验证声明，不重跑确定性校验：producer 已自跑修到全绿，同脚本跑两遍结果必然相同）**。producer 按约回报四数（SQL 文件数 / 断言式与对比式条数 / 歧义标注数 / declined 数），对账磁盘事实：

- `dq/` 下 .sql 文件数 = 回报数 = dq.json rules 条数；
- 歧义数 / declined 数 = dq.json 两数组长度（闸口② 材料，必须点名核对）；
- ts.md DQ 章节在位（= 装配渲染真发生过，防没跑装配就自称全绿）。

**对不上才恢复 producer 会话**（带差异清单一次修完，限 3 轮），此时才有必要重跑全量校验：

```bash
python DQ_SCRIPTS/assemble_dq.py --ts {deliver}/ts.json --dq-src {deliver}/dq.json \
    --rs {deliver}/_internal/rs_input.json
```

补全（idx/文件名/mode 缺省/meta+dq 调度任务）+ 校验（文件在位/引用对账/禁 tmp/幻觉列/SQL 风格项）+ ts.md 追加 DQ 表格（主线章节字节不动，含歧义标注与 declined 建议不做段）。**DQ 设计材料归闸口②**——与执行结果同屏判读（审口径时直接看跑出来的数字）。

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

### 步骤 5a：UT 预检（EXPLAIN ANALYZE 全量真实执行，时长≈一次 SELECT）

回退 + DDL + SELECT 预检。不写数据，只验证建表和查询能跑通。

```bash
python PIPE_SCRIPTS/ut_precheck.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --result {deliver}/_internal/ut_precheck_result.json
```

**读预检结果**：全通过 → 继续 5b；有失败 → 走步骤6 分流（SQL 问题回 coder / 环境问题报告人）。

预检用 **EXPLAIN ANALYZE 全量真实执行一次（不带采样）**——一次执行三份收获：真跑通验证（采样过≠全量过）+ **执行计划两门槛**（①不下推=官方判据 `Data Node Scan`/`_REMOTE_TABLE_QUERY_`；②STREAM 算子数 ≤50 含 PART 变体）+ 顶层实际行数（0 行=空关联极端信号，全量口径）。行数解析多格式兼容（PG 文本式/表头驱动表格式），解析不出宁缺勿错跳过不猜；**计划原文（含 actual 值）全量落盘** `_internal/diagnose/plan_{rule}.txt`（过程可视）；两门槛提示级不阻断，性能归闸口②人判。**字段级 NULL（LEFT JOIN 关联不上的常态形态：行数正常+关联字段全 NULL）本检查拿不到列值——6b INSERT 后空值检查兜底**。

### 步骤 5b：UT 执行（慢，分钟级）

按 load_mode 预处理 + INSERT 灌数据 + UT 检查 + 出报告。

```bash
python PIPE_SCRIPTS/ut_execute.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl \
  --ddl-dir {deliver}/ddl \
  --precheck-result {deliver}/_internal/ut_precheck_result.json \
  --report {deliver}/ut_report.md
```

> ⚠️ `--precheck-result` 路径与 5a 的 `--result` 一致（都在 `_internal/` 下）。读不到直接退出（避免预检未通过误灌数据）。
> **超时**：预检/执行都可能跑数分钟，调脚本设 timeout=600000ms（数据库端 statement_timeout 自动兜底）。
> ★ 6b 无采样闸门：6a 预检已全量真实执行 SELECT，INSERT 侧值域错误由值域探测+溢出路由兜底——直接 TRUNCATE+全量 INSERT。
> ★ **init 资产的 UT 顺序**：有 `init` 段时，ut_precheck/ut_execute 自动**先跑 init 阶段（truncate+全量插建基线），再跑增量阶段（在基线上 merge）**。无需分开调，脚本内部有序两阶段；init 挂了基线就废，后续增量自动跳过。
> ★ **DQ 检查内嵌 5b 尾部**（`dq.json` 有规则且数据完整时自动执行；旧资产兼容读 ts.dq_rules）：0 行=通过，非 0 行=告警。告警/报错阻断出口（exit 1），UT 报告有 DQ 段（对比式 0 行带双义提示）——分流见步骤 6。

---

## 步骤 6：执行回路（如有失败）

读 UT 报告，**按失败项类型分流**：

> ⚠️ 数据质量类失败（主键重复/空值/行数异常）一律**不回 coder**——coder 会用 ROW_NUMBER 去"消除症状"掩盖根因（关联发散）。这类根因在设计层，退回 designer。

> ⚠️ **类型转换类报错（含 invalid input syntax / operator does not exist）先看报告的"嫌疑报告"段再分流**：有关联键嫌疑（类型跨大类的 JOIN 对）→ 退 designer/人核对关联逻辑，**★禁止用改字段类型来"修复"**（掩盖根因，同 ROW_NUMBER 反模式）；无关联嫌疑才走 6a/6b。
> ⚠️ **值域溢出类报错（numeric field overflow / value too long）禁回 coder**——处理按步骤 1b「值域溢出处理菜单」分角色二选一（①BA 改 mapping 目标类型重跑 1a+1b；②SE 拍板置空/截断→designer 写显式口径→coder 实现）。菜单唯一源在 1b，此处不复述。

**6a. SQL 问题 → coder**（INSERT 报错含 COLUMN/TYPE/SYNTAX/DOES NOT EXIST，或预检 FAIL）。
恢复该规则 coder 旧会话（task_id 在步骤4b 记的映射里）：
```
Task(subagent_type="dws-coder", task_id="{该规则 task_id}",
     description="修复 {rule_code} SQL 报错",
     prompt="{rule_code} 执行报错：{报错信息}。请修正 SELECT。")
```
改完重跑步骤5。**每规则限 3 轮**。

**6a-DQ. DQ 段 FAIL/MISSING（SQL 执行报错/文件缺失）→ 恢复 dws-dq-producer 会话修**（短会话分钟级；改完只重跑 UT 的 DQ 段，不重跑装载）。**限 3 轮**。

**6a-DQ-ALERT. DQ 告警（ALERT，非 0 行）→ 攒闸口② 人判，零自动回路**（不让 producer 迭代语义问题——它改不出"通过"只会空转）。UT 报告 DQ 段带违规行样例，闸口② 人三选一：①SQL 写错 → 恢复 producer 改该条；②检查不合理 → 人定新口径（producer 照译，不自己想口径）或取消该条；③数据真脏但检查保留 → 豁免（dq.json 标 waived+理由）。**对比式 0 行也进闸口② 材料**（双义提示：口径一致通过 / 口径写错恒等失效，人审口径）。

**6b. 数据质量问题 → 人确认根因 → （要改设计才回 designer）→ coder**。
INSERT 成功但 UT 检查 FAIL（主键重复/空值/行数异常，报告带样例数据）。

> ★ **不回退 designer 诊断给方案**。designer 基于自己的设计立场会给偏向性结论（如"改 join_safety 加 GROUP BY / 改 business_key"），这俩方案往往站不住脚——前者掩盖 JOIN 发散丢数据，后者是凑假主键。根因判断（设计问题 / 环境数据脏 / 业务一对多）需要业务认知，是人的领域。

⓪ **主键重复类失败先跑发散定位**（事实进问题，人判断质量高）：

```bash
python PIPE_SCRIPTS/diagnose_fanout.py --ts {deliver}/ts.json --rule {rule_code}
```

关联质量一次拿全（**只反馈事实，不猜收敛方式**）：**逐表键唯一性=主判据**（每表必跑：条件下唯一=一句话通过+声明对照标签[一致/△漏条件人核/△自创/自然语言跳过/中间表正常/输入未声明]；不唯一=展开证据块——关联条件原文+输入声明对照+join_safety 断言对照[声明 unique 实测不唯一=证伪] +重复键+重复组差异列+命中，人判设计侧还是数据脏）+ **整体试算严重性**（按声明条件拼全链数行数：膨胀/丢行/空关联率——全通过却膨胀=矛盾信号，贴全部条件原文人判）+ 字面量值形态开局修正（char 列裸数值=声明错误披露）。中间表规则闸口①不可查（表未建，UT 兜底）。报告分规则**全量**落盘（中间结论不吞）；exit 2=无库归 6c。**单表故障隔离**：某表查询失败不炸整批——降级不带条件查/跳过续跑，报错原文与隐式转换提示照常披露。

① **主控读 UT 报告**（含重复键+样例+开发环境数据免责提示+⓪ 定位结论），用 question 问人根因：
```
question("{rule_code}（{target}）UT 主键检查失败：{失败项+样例，摘 UT 报告}\n"
         "发散定位：{⓪ 工具结论一行——不唯一表+断言证伪/矛盾信号/全部通过}\n"
         "请确认根因是哪种：\n"
         "  - 关联设计问题（JOIN 发散，需调整关联/限定条件）\n"
         "  - 源表数据问题（源端一对多/脏/关联声明与数据不符——退 BA 修输入后重跑 1a 全流程，现实中大概率此项）\n"
         "  - 业务粒度问题（业务上一对多，business_key 该补行字段——需与 BA 确认）\n"
         "  - coder 实现与设计不符（如漏了 GROUP BY）",
         options=["关联设计问题", "源表数据问题(退BA)", "业务粒度问题", "coder实现不符"])
```
> 开发环境数据量/质量与生产不一致，不能仅凭 UT 结果下结论。

② **按人定的根因分流**：
- **源表数据问题（退 BA）** → 输入侧问题：人协调 BA 修源端（数据治理/关联声明/粒度确认），改后重跑 1a 全流程；开发库临时脏数据也可选择先治理环境再重跑 UT（基础设施类故障才归 6c）
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
python PIPE_SCRIPTS/assemble_export.py \
  --ts {deliver}/ts.json \
  --etl-dir {deliver}/etl/ \
  --outdir {deliver}
```

产出在 `{deliver}/export/` 下：
- `shujia_{表名}.xlsx`（术加执行平台导入，10 sheet）
- `lts_{表名}.xlsx`（LTS 调度平台导入，3 sheet）

> 编码列为占位符（组码 `GR_*`、规则码 ts 码、pv 行 `PV000N`），出厂已做三处闭合校验；子项目中文名留空人填。
> 命令末尾输出**制品完整度报告**（固定格式待补清单）——它是闸口②后固定二选一的问题清单来源，转述给人即可。
> **★ 铁律（值来源三通道）**：制品中占位符/空值的唯一来源是——①人在"补充项目信息"里提供、
> ②内网取码脚本回填（`SHARED_SCRIPTS/local/backfill_rule_codes.py`，内网环境）、③保持占位出厂。
> **engineer 永不生成、不推测、不"建议填充"这些值**——哪怕看起来能从表名推出来。

---

## 步骤 8：闸口②（人确认编码质量）

**必须调 question 展示结果摘要等用户确认**（摘要含 UT 通过/失败数 + **DQ 材料：ts.md DQ 表格的设计部分（对比式口径/歧义裁决点/declined 建议不做——producer 独立理解与 designer 口径并排，理解差=mapping 歧义）与执行结果（0 行=通过；有告警必须列样例与去向判断）同屏** + 产出文件清单），跑完必须停下，不允许自己结束流程：

- 用户选「**确认，结束**（第一选项·默认推荐）」→ 制品以占位符形态出厂，**直接建档结束**：
  完整度报告已随步骤7输出（转述即可）；待补项由内网取码脚本回填或导入前人工补——
  人拿终版完整包后建议存回 `{deliver}/../archive/export/` 覆盖同名（档案升级为完整态）。
- 用户选「**确认，补充项目信息**」→ 按**固定清单**逐项收集（清单=完整度报告内容，每次一样；
  每项可答"跳过"，跳过即保持占位，**不追问不代答**）→ 按固定落点填入 → 重出制品 → 建档结束：
  1. 项目编码 / 项目英文名 → 写入 shujia_config 租户块（补一次后续资产复用）；
  2. 子项目中文名 → 重出参数 `--sub-project-cn`；
  3. 规则组编码（init 组如有）→ 重出参数 `--group-code` / `--init-group-code`；
  4. depTaskId（如有跳过）→ 写入 lts_config 的 dep_task_ids（键=报告里给的四段键）；
  5. 重跑 assemble_export（带上述参数）→ 建档。
- 用户选「**确认，内网完善**」（内网环境且 backfill 脚本就位时才展示）→ 完善链（engineer 驱动，
  **无等待环节**）→ 完整包落位 build/export/ → **直接建档**（档案从第一天就是完整态）：
  1. question 收集脚本补不全、必须人给的（项目中文名+子项目中文名）；
  2. 跑 `SHARED_SCRIPTS/local/backfill_rule_codes.py`（术加平台：模拟网页取编码/取依赖/可选上传；
     LTS 同类脚本待建，建好后接入）；
  3. 脚本不在则告知手工，转「确认，结束」分支。
- 用户选"修改"（说明哪里改）→ 回对应步骤（编码问题回 coder / 设计问题回 designer）
- 用户选"放弃" → 结束（**不建档**——build/ 工作区留草稿，重跑覆盖；档案被动过则停问人）

**建档（两个确认分支的收尾，脚本做）**：

```bash
python SHARED_SCRIPTS/archive_writer.py adopt --build {deliver}
```
  从 build/ **复制**本源件（ts/dq.json/etl/dq/ddl/export + decisions）生成 `{deliver}/../archive/` + MANIFEST 首建（v1 建造）；
  build/ 保留完整交付现场（全量部署内容：DDL/SQL/制品包/报告——人拿一个目录即可部署当前版本；下次优化开工清场重建）。此后资产有档、可优化。

> 非交互例外同闸口①（仅显式声明时跳过；人工决策项不豁免，见步骤 3 的非交互条款）。
> 非交互下走"直接建档"分支（无等待语义；产物人后审=审归档后形态），完善推后+回流兜底。

---

# 硬性规则

- 闸口①确认后**自动进编码段**，中间不交接
- **步骤4 编码段并行发起**：4a/4b/4c 同消息并行（互不依赖），4d 等 4b 增量规则完成
- 记住每个 coder 的 task_id（步骤6 执行回路靠 task_id 恢复会话，不新开）
- **未经用户确认不结束流程**；全程中文
