---
name: opt-pipe
description: >-
  优化交付全流程剧本（dws-engineer 加载执行）：入口基线→输入校验→增量设计→围栏→闸口①'→
  编码→SQL围栏→DDL→UT→闸口②'→制品patch→档案推进。存量资产精确变更（第一刀 add_field）。
  新建场景不在此（new-pipe）。
---

# 优化交付全流程剧本（dws-engineer 执行）

> 任务参数（模式/mapping/rs/交互）由 dws-engineer 解析后进入本剧本；红线与编排者铁律见岗位定义（agents/dws-engineer.md），此处不复述。输入文件路径是契约参数（mapping/rs 直传，无分拣）。

## 目录与档案（基石定调，2026-08-31）

```
10_project_deliver/{appid}/{schema}/{资产=I名}/ddlc_design_dev/
├── archive/          ← ★资产档案=当前态唯一真身（入 git；ts.json/ts.md/etl/{rule}.sql/
│                       ddl//dq//decisions.yaml）。演进史=git 提交历史（每次交付覆盖+commit）。
│                       确认前零改动=天然回归点（放弃优化=扔掉 opt/ 现场，档案无损）。
├── export/ ut_report.md   ← new-pipe 交付现场（收档后留原位）
├── _internal/             ← new-pipe 过程产物（收档后留原位）
└── opt/             ← 本次优化更新（每次开工重建；gitignore）
    ├── ts_v2.json / ts.md / etl/（新 SQL {rule_code}.sql）/ ddl/（ALTER 变更单+I视图重建）
    ├── export/（patch 副本+notes）/ ut_report_opt.md
    └── _internal/（baseline_v1.json / baseline_view.md / exemptions.json /
                    change_request.json / design_decisions_opt.yaml / diagnose/）
```

- **资产标识 = mapping 声明的目标表**（正常 I 视图名；只存 F 的资产即 F 名——按人写的算）。
- baseline = **archive/ 本体**（脚本只读消费，无快照拷贝；写坏有 git 兜底）。
- 档案两动作（archive_writer 子命令）：`adopt` 首优收档 / `advance` 交付收口（闸口②'确认后）。
- 脚本路径：`PIPE_SCRIPTS` = `{SKILL_BASE}/scripts`（preprocess_opt/fence_check/sql_fence_check/ut_opt/assemble_ddl_opt/assemble_ts_baseline/artifact_patcher/archive_writer），`SHARED_SCRIPTS` = `{SKILL_BASE}/../design-dev-shared/scripts`（preprocess/check_db + 公共库），bash 用绝对路径。

---

## 步骤 0：环境自检 + 入口与基线

0. 环境探针（一次）：`python {SKILL_BASE}/../new-pipe/scripts/check_env.py`——exit 1 = 环境/依赖不符 → 停。工具面自检同 new-pipe 步骤0。
1. 按资产定位：`python SHARED_SCRIPTS/preprocess.py --mapping {mapping} --rs {rs} --probe` → asset/appid/schema → `{ddlc}` = `10_project_deliver/{appid}/{schema}/{asset}/ddlc_design_dev`，`{arc}` = `{ddlc}/archive`，`{opt}` = `{ddlc}/opt`。
2. **清场重建 {opt} 目录树**（每次开工：上次现场的 ALTER 单/patch 副本残留会混入本次交付物误导执行——清掉重来；交付物在流程结束人已执行完，无损失）：`rm -rf {opt} && mkdir -p {opt}/etl {opt}/ddl {opt}/export {opt}/_internal/diagnose`（空目录=进度看板）
3. **查基线（三段式）**：
   - **`{arc}/ts.json` 存在** → 有档，直接当 baseline。跳到步骤 1。
   - **无档但 `{ddlc}/ts.json` 存在**（new-pipe 平铺产出，未优化过）→ **首优收档**：

```bash
python PIPE_SCRIPTS/archive_writer.py adopt --ddlc {ddlc}
```
     收档收 ts/etl/dq/**export**/decisions（**ddl 不入档**——ts 的可再生投影，留交付现场）；git 提交由人按自己的节奏做。跳到步骤 1。
   - **都没有** → 要求 baseline_v1.json（用户给路径；没有则停：指引"先由逆向侧产出"）。入料建档：

```bash
python PIPE_SCRIPTS/assemble_ts_baseline.py \
  --baseline {baseline_v1.json} --archive-dir {arc} --internal-dir {opt}/_internal
```
     档案件（ts.json + etl/{rule}.sql）落 `{arc}`，过程件（baseline_view.md + exemptions.json）落 `{opt}/_internal`。exit 2 = 契约违约 → 停，报告（契约问题归逆向侧）。

## 步骤 1：优化输入预处理（契约参数直传）

⚠️ **输入文件禁止 Read**——解析/校验全由脚本消化（对齐"输入原文一律不 Read"），你只消费 change_request。

```bash
python PIPE_SCRIPTS/preprocess_opt.py \
  --mapping {mapping} --rs {rs} \
  --ts-baseline {arc}/ts.json \
  --outdir {opt}/_internal [--version 202608]
```
- 版本锚点：默认取 RS 变更记录最新"优化"行日期归一 YYYYMM（撞车/缺行 → --version 显式指定）；
- 变更提取：mapping 备注列 `{YYYYMM}版本{动词}` 匹配本次版本——属性级"新增"= 新增字段候选、实体级"新增"= 新来源；**其他动词（修改/下线…）识别归类并报告"待扩展"，不是非法输入**；
- exit 2 = 阻断（冲突/别名悬空/资产不一致[已按 I/F 镜像归一比较]/版本定位失败）→ 报告人改输入，不自动修；
- exit 1 = 有 warn（漏标漂移/RS 未提及）→ 展示后**直接继续**（信息性告知，随 change_request 汇进闸口①'材料）；
- 产出 `change_request.json`（含 version/变更记录摘要——闸口①'把简述与提取字段并排亮给人扫漏标）。

## 步骤 1b：优化预检（只检新增子集，对齐 new-pipe 1b）

```bash
python PIPE_SCRIPTS/precheck_opt.py \
  --change-request {opt}/_internal/change_request.json \
  --ts-baseline {arc}/ts.json \
  --outdir {opt}/_internal
```
- 检查项：新增字段命名规范 / 源字段连库存在性+类型对账（**以库为准**修正回填）/ 类型风险决策（人三选：转换/不加/返源端）/ 值域探测（整数位溢出退 BA、字符超长披露）/ 新来源 JOIN 键类型对账（三选：转换/改关联键/接受）。存量零预检（围栏+双跑兜底）。
- stdout `TYPE_RISK_PENDING` / `JOIN_TYPE_RISK_PENDING` → **用 question 收集决策再填**（同 new-pipe 1b：`python SHARED_SCRIPTS/fill_type_risk_decision.py --decision {opt}/_internal/type_risk_decision.yaml ...`），填完**重跑本步**放行。批量按类型对归并提问；`返源端`/`改关联键` = **本轮终止**（修 mapping/源端后重跑步骤 1）。
- 决策回写 change_request（fields『decision』标记 + join_type_decisions）——designer 见标记勿推翻方向。
- exit 2 = 阻断（命名/存在性/决策未过）→ 按 diff 报告人改输入，不自动修；exit 1 = warn 直接继续。无库降 warn（UT 兜底）。

## 步骤 2：designer（优化模式，显式声明）

```
Task(subagent_type="dws-designer", description="优化模式设计 {资产}",
  prompt="优化模式：加载 dws-design-opt skill。读 {opt}/_internal/baseline_view.md 与
          change_request.json，按 opt-decisions-template 写增量设计决策到
          {opt}/_internal/design_decisions_opt.yaml，然后调 assemble_ts_opt 组装
          {opt}/ts_v2.json。新 JOIN 必须声明 join_safety；发现存量问题走回报不直改。")
```
记下 designer 的 task_id（回路用）。验证 `{opt}/ts_v2.json` + `ts.md` 已产出。

## 步骤 3：ts 级围栏 → 闸口①'

```bash
python PIPE_SCRIPTS/fence_check.py \
  --ts-baseline {arc}/ts.json --ts-v2 {opt}/ts_v2.json \
  --change-request {opt}/_internal/change_request.json
```
- 越界/漏改（exit 1）→ 报错带 `[围栏]` 回 designer（恢复会话）改，限 3 轮；designer 提的
  【建议追加变更】走本闸口确认后更新 change_request 再回步骤 2。
- **闸口①' 材料（确定性脚本产出，不 AI 摘要）**：

```bash
python PIPE_SCRIPTS/gate_summary_opt.py \
  --ts-v2 {opt}/ts_v2.json --ts-baseline {arc}/ts.json \
  --change-request {opt}/_internal/change_request.json
```
- **闸口①'（question，三问）**：① 落位确认（拿 gate_summary_opt 的逐字段落位表："X 挂 R00xx，新 JOIN T，中间表不动/加列——确认？"）
  ② 回刷选择（增量基线才有；RS 已预填则确认）③ 建议追加的变更（如有）。
  **分场景模板**：围栏/预检全干净 → 三问标准选项（确认/修改/放弃）；**检出过问题**（围栏越界/类型风险决策/值域披露/新 JOIN 类型）→ 四选项，必含**"源端输入问题→退 BA（修 mapping/源数据后重来）"**一等选项（现实大概率是源端问题；与 new-pipe 闸口①同款）。
  非交互跳过须显式声明（只豁免流程闸口；人工决策项照常阻断上报）。

## 步骤 4：编码（SQL 围栏闸门在你）

对 change 段 placed_rules 的每条规则**并行**发起 coder：

```
Task(subagent_type="dws-coder", description="优化编码 {rule_code}",
  prompt="优化模式：加载 dws-coding-opt skill。ts_v2 路径 {opt}/ts_v2.json，
          规则 {rule_code}，baseline SQL 在 {arc}/etl/{rule_code}.sql（档案只读勿改；
          切片加 --baseline-sql 参数）。以底稿加列，老列投影不许动，
          产出到 {opt}/etl/，文件名 {rule_code}.sql（与档案同名=该规则当前版）。")
```
每规则记 task_id。全部落盘后**你独立跑 SQL 围栏**（对每条 placed_rule，闸门单点在你）：

```bash
python PIPE_SCRIPTS/sql_fence_check.py \
  --ts-v2 {opt}/ts_v2.json --etl-dir {opt}/etl \
  --baseline-dir {arc}/etl
```
越界/漏改（exit 1）→ `[SQL围栏]` 报错回该规则 coder（恢复会话）改，限 3 轮。结果落盘
`_internal/sql_fence_result.json`——**回路铁律已机器化**：ut_opt 开跑校验围栏时效，SQL 晚于围栏结果 = 拒跑（exit 2，先重跑本步）。

## 步骤 5：DDL 变更单 → UT（需要数据库）

**先产 ALTER 变更单**（UT 依赖它应用新列；缺了 UT 会 fail loud 拒跑）：

```bash
python PIPE_SCRIPTS/assemble_ddl_opt.py \
  --ts-v2 {opt}/ts_v2.json --ts-baseline {arc}/ts.json --outdir {opt}
```
产出 `{opt}/ddl/alter_table_*.sql`（变更单）+ `create_or_replace_view_*.sql`（I 视图重建——F 表加列后镜像须同步，如有 i_view）。全量建表 DDL 不产（ts 的可再生投影）。

```bash
python SHARED_SCRIPTS/check_db.py --ts {opt}/ts_v2.json
```
NO_DB_SOURCE → 跳过 UT（闸口②告知），直接步骤 6。DB_OK：

```bash
python PIPE_SCRIPTS/ut_opt.py \
  --ts {opt}/ts_v2.json --etl-dir {opt}/etl \
  --baseline-dir {arc}/etl --ddl-dir {opt}/ddl \
  --report {opt}/ut_report_opt.md
```
- exit 2 = ALTER 变更单缺失（流程顺序错，回本步骤头部补跑 assemble_ddl_opt）；
- exit 3 = 环境问题（表不存在/无库）→ 归人；
- 每规则 EXPLAIN ANALYZE 真实执行一次（计划两门槛 + 0 行信号，计划落盘 diagnose/）+
  **新列空值检查**（写路径后真实数据；全 NULL = 疑似新 JOIN 关联不上——闸口②'素材）；
- 对比 FAIL（老列不一致）/ 新列全 NULL → **先跑定位工具产证据，再 question 人定根因**：

```bash
python PIPE_SCRIPTS/diagnose_fanout_opt.py --ts-v2 {opt}/ts_v2.json [--rule {rule}]
```
  （逐表键唯一性主判据 + join_safety 断言对照，证据落盘 diagnose/fanout_{rule}.md）

**UT 失败分流表**（按表路由，不发明表外动作）：

| 类型 | 识别 | 去向 |
|------|------|------|
| SQL 报错 | 新 SELECT/INSERT 报错含 COLUMN/TYPE/SYNTAX | 回该规则 coder（恢复会话），限 3 轮 |
| 对比 FAIL | 冻结列回归失败（老列不一致） | question 人定根因：新 JOIN 发散=设计问题（改法→回 designer→回闸口①'重确认→SQL 围栏重跑→UT 重跑）；源数据=环境归人 |
| 新列全 NULL / 0 行 / 计划门槛 | 提示级（披露不代答） | 闸口②'人判（关联不上→designer 核 ON；数据真缺→人定） |
| 环境问题 | ALTER 失败/表不存在/无库（exit 3） | 归人，不回调 agent |

## 步骤 6：制品

```bash
python PIPE_SCRIPTS/artifact_patcher.py \
  --ts-v2 {opt}/ts_v2.json --etl-dir {opt}/etl \
  --source {原始制品：xlsx 或代码仓规则组目录} \
  --outdir {opt}/export
```
`--source` 定位顺序：**`{arc}/export/`（档案的制品当前态——patch 链底本，首选）** → ts_v2 的 `_baseline.provenance`（逆向入料带的原始路径）→ 取不到问人。
产出：`{opt}/ddl/alter_table_*.sql`（变更单）+ view 重建 + `{opt}/export/patched/`（更新后制品副本）+ `patch_notes.md`。patch 缺失/定位失败项照 notes 报告，不自动补。

## 步骤 7：闸口②' → 档案推进

**闸口②'（question）**：① 新列结果合理性（ut_report_opt 的 NULL 率/差集样例一屏）
② 交付物清单确认（ALTER 变更单 + 新 SQL + patched 副本 + patch 说明 [+回刷意向如有]
+ 资产健康提示 = baseline warnings 摘要一屏）。确认后**交付收口**（推进档案）：

```bash
python PIPE_SCRIPTS/archive_writer.py advance --opt {opt} --archive {arc}
```
ts_v2/ts.md/新 SQL（同名覆盖）/export/patched 制品副本/decisions_opt → 档案当前态推进（DDL 不入档）；`{opt}/` 现场保留（交付物在人取用），下次优化开工重建。git 提交由人按自己的节奏做（流程不内嵌 git 操作）。流程结束，人拿交付物去执行（推生产不自主）。

## 硬性规则

- **围栏永远在 UT 之前**；产物变了（SQL/ts）→ 对应层围栏重跑 + UT 重跑
- **档案（{arc}/）确认前零改动**——所有工作产物只进 {opt}/；回归=放弃 {opt}/ 现场
- 不调任何逆向侧脚本；不验真输入（缺 json/档案不存在 = 停 + 指引）
- 记所有 agent task_id；失败恢复旧会话不新开；每规则限 3 轮
- 未经用户确认不结束流程；全程中文
