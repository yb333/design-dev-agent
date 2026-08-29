---
name: opt-pipe
description: >-
  优化交付全流程剧本（dws-engineer 加载执行）：基线→输入校验→增量设计→围栏→闸口①→
  编码→SQL围栏→UT→闸口②→制品patch→归档。存量资产精确变更（第一刀 add_field）。
  新建场景不在此（new-pipe）。
---

# 优化交付全流程剧本（dws-engineer 执行）

> 任务参数（模式/mapping/rs/资产/交互）由 dws-engineer 解析后进入本剧本；红线与编排者铁律见岗位定义（agents/dws-engineer.md），此处不复述。**存量基线的定位**（baseline_v1.json 仅外部资产首次；自建/已优化资产走档案）从需求包目录与档案库推导，缺基线即停并指引。

## 概念速查

- **唯一锚点 = 资产档案**（`archives/{schema}/{资产}/{NNN_日期}/`）：有档 → 档案即 baseline（零组装）；无档 → 收 json 入料建档。**不调用逆向脚本**（peer agent，文件交接）。
- **两级声明**：change_request（业务说了什么，脚本产）+ ts.change（落位，designer 产）→ 围栏许可 = 两者合体。
- **三段审计**：意图→落位（fence 内含）→ 结构（fence_check）→ 代码（sql_fence，**闸门单点在你**）。
- 产出目录 `{deliver}` = `10_project_deliver/{appid}/{schema}/{资产}/ddlc_opt/`（资产名/schema/appid 全从输入推导：preprocess --probe，同 new-pipe——调用方不传）。
- 脚本路径定位：同 new-pipe 剧本的「脚本路径定位」段——从本 skill 的 Base directory 推算（`{SKILL_BASE}/../design-dev-shared/scripts` 等，bash 用绝对路径）。

---

## 步骤 0：入口与基线

1. 按资产定位 `{deliver}`：`python SHARED_SCRIPTS/preprocess.py --mapping {需求包内mapping} --rs {RS} --probe` → asset/appid/schema 定位（同 new-pipe）。
2. **查基线（三段式）** `archives/{schema}/{资产表}/`：
   - **有档案** → 最新目录即基线：`ts_baseline.json` = 档案 ts，`etl_baseline/` = 档案 etl/。跳到步骤 1。
   - **无档案，但 `10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/` 有 new-pipe 产出** → **懒归档**（建档案的成本只在真正优化时付，new-pipe 不做归档步骤）：

```bash
python SHARED_SCRIPTS/archive_writer.py \
  --ts {new-pipe交付目录}/ts.json --etl-dir {new-pipe交付目录}/etl \
  --ddl-dir {new-pipe交付目录}/ddl \
  --decisions {new-pipe交付目录}/_internal/design_decisions.yaml \
  --archives-root archives
```
     然后按"有档案"处理。
   - **都没有** → 要求 baseline_v1.json（用户给路径；没有则停：指引"先由逆向侧产出"）。然后入料建档：

```bash
python SHARED_SCRIPTS/assemble_ts_baseline.py --baseline {baseline_v1.json} --outdir {deliver}/_internal
```
   产出 ts_baseline.json + etl_baseline/ + baseline_view.md + exemptions.json。exit 2 = 契约违约 → 停，报告（契约问题归逆向侧）。

## 步骤 1：优化输入预处理（真实格式：全量 mapping 备注版本标记 + RS 变更记录）

⚠️ **需求包目录下的任何文件禁止 Read**——分拣/解析/校验全由脚本消化（对齐 new-pipe"输入原文一律不 Read"），你只消费 manifest 与 change_request。

```bash
python SHARED_SCRIPTS/preprocess_opt.py \
  --input-dir {需求包目录} \
  --ts-baseline {deliver}/_internal/ts_baseline.json \
  --outdir {deliver}/_internal [--version 202608]
```
- 分拣：唯一 xlsx = 全量 mapping、唯一 md = RS（多个按文件名关键词 full/最新/融合 与 rs/需求；分不出 fail loud；`--full-mapping/--rs` 可显式覆盖）；
- 版本锚点：默认取 RS 变更记录最新"优化"行日期归一 YYYYMM（撞车/缺行 → --version 显式指定）；
- 变更提取：mapping 备注列 `{YYYYMM}版本{动词}` 匹配本次版本——属性级"新增"= 新增字段候选、实体级"新增"= 新来源；**其他动词（修改/下线…）识别归类并报告"待扩展"，不是非法输入**；
- exit 2 = 阻断（冲突/别名悬空/资产不一致/版本定位失败）→ 报告人改输入，不自动修；
- exit 1 = 有 warn（漏标漂移/RS 未提及）→ **question 问人**是否继续；
- 产出 `input_manifest.json`（分拣依据，可追溯）+ `change_request.json`（含 version/变更记录摘要——闸口①'把简述与提取字段并排亮给人扫漏标）。

## 步骤 2：designer（优化模式，显式声明）

```
Task(subagent_type="dws-designer", description="优化模式设计 {资产}",
  prompt="优化模式：加载 dws-design-opt skill。读 {deliver}/_internal/baseline_view.md 与
          change_request.json，按 opt-decisions-template 写增量设计决策到
          {deliver}/_internal/design_decisions_opt.yaml，然后调 assemble_ts_opt 组装
          {deliver}/ts_v2.json。新 JOIN 必须声明 join_safety；发现存量问题走回报不直改。")
```
记下 designer 的 task_id（回路用）。验证 ts_v2.json 已产出。

## 步骤 3：ts 级围栏 → 闸口①

```bash
python SHARED_SCRIPTS/fence_check.py \
  --ts-baseline {deliver}/_internal/ts_baseline.json --ts-v2 {deliver}/ts_v2.json \
  --change-request {deliver}/_internal/change_request.json
```
- 越界/漏改（exit 1）→ 报错带 `[围栏]` 回 designer（恢复会话）改，限 3 轮；designer 提的
  【建议追加变更】走本闸口确认后更新 change_request 再回步骤 2。
- **闸口①'（question，三问）**：① 落位确认（"X 挂 R00xx，新 JOIN T，中间表不动/加列——确认？"）
  ② 回刷选择（增量基线才有；RS 已预填则确认）③ 建议追加的变更（如有）。非交互跳过须显式声明（只豁免流程闸口；人工决策项照常阻断上报）。

## 步骤 4：编码（SQL 围栏闸门在你）

对 change 段 placed_rules 的每条规则**并行**发起 coder：

```
Task(subagent_type="dws-coder", description="优化编码 {rule_code}",
  prompt="优化模式：加载 dws-coding-opt skill。ts_v2 路径 {deliver}/ts_v2.json，
          规则 {rule_code}，baseline SQL 在 {deliver}/_internal/etl_baseline/{rule_code}.sql
          （切片加 --baseline-sql 参数）。以底稿加列，老列投影不许动，产出到 {deliver}/etl/。")
```
每规则记 task_id。全部落盘后**你独立跑 SQL 围栏**（对每条 placed_rule，闸门单点在你）：

```bash
python SHARED_SCRIPTS/sql_fence_check.py \
  --ts-v2 {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --baseline-dir {deliver}/_internal/etl_baseline
```
越界 → `[SQL围栏]` 报错回该规则 coder（恢复会话）改，限 3 轮。**回路铁律：任何 SQL 变化后重跑本步再进 UT。**

## 步骤 5：UT（需要数据库）

```bash
python SHARED_SCRIPTS/check_db.py --ts {deliver}/ts_v2.json
```
NO_DB_SOURCE → 跳过 UT（闸口②告知），直接步骤 6。DB_OK：

```bash
python SHARED_SCRIPTS/ut_opt.py \
  --ts {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --baseline-dir {deliver}/_internal/etl_baseline --ddl-dir {deliver}/ddl \
  --report {deliver}/ut_report_opt.md
```
- exit 3 = 环境问题（表不存在/无库）→ 归人（对齐 new-pipe 6c）；
- 对比 FAIL（老列不一致）→ **question 人定根因**：新 JOIN 发散=设计问题（人定改法→回 designer→
  回闸口①'重确认→SQL 围栏重跑→UT 重跑）；源数据问题=环境归人；
- SQL 报错 → 回 coder。限 3 轮。

## 步骤 6：制品

```bash
python SHARED_SCRIPTS/assemble_ddl_opt.py \
  --ts-v2 {deliver}/ts_v2.json --ts-baseline {deliver}/_internal/ts_baseline.json \
  --outdir {deliver}
python SHARED_SCRIPTS/artifact_patcher.py \
  --ts-v2 {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --source {原始制品：xlsx 文件或代码仓规则组目录（provenance 定位）} \
  --outdir {deliver}/export
```
产出：`ddl/alter_table_*.sql`（变更单）+ `ddl_full/`（档案用）+ `export/patched/`（更新后制品副本）
+ `export/patch_notes.md`。patch 缺失/定位失败项照 notes 报告，不自动补。

## 步骤 7：闸口② → 归档

**闸口②'（question）**：① 新列结果合理性（ut_report_opt 的 NULL 率/差集样例一屏）
② 交付物清单确认（ALTER 变更单 + 新 SQL + patched 副本 + patch 说明 [+回刷脚本如有]
+ 资产健康提示 = baseline warnings 摘要一屏）。确认后：

```bash
python SHARED_SCRIPTS/archive_writer.py \
  --ts {deliver}/ts_v2.json --etl-dir {deliver}/etl --ddl-dir {deliver}/ddl_full \
  --decisions {deliver}/_internal/design_decisions_opt.yaml --archives-root archives
```
档案当前态推进（v1.7 循环链闭合），流程结束。人拿交付物去执行（推生产不自主）。

## 硬性规则

- **围栏永远在 UT 之前**；产物变了（SQL/ts）→ 对应层围栏重跑 + UT 重跑
- 不调任何逆向侧脚本；不验真输入（缺 json/档案不存在 = 停 + 指引）
- 记所有 agent task_id；失败恢复旧会话不新开；每规则限 3 轮
- 未经用户确认不结束流程；全程中文
