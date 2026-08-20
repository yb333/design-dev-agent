---
status: active
last_reviewed: 2026-08-19
depends_on: [../specs/opt/00-总纲与范围.md]
edition: 实现版（v2，2026-08-19 建成后重写；设计过程版见 git 历史与 specs/opt 系列）
---

# 优化场景架构与操作手册（opt，实现版）

> 本文是优化场景的**单一现状参考**：架构、流程（含真实命令）、组件清单、目录约定、机制说明——全部以已建成并通过测试（1001 pytest）的代码为准。设计推演过程与原则全文在 `docs/specs/opt/00-08`；端到端测试入口在 `11-测试指引`。
> **定位**：实测优化场景期间的权威手册；实测通过后与 `architecture.md`（新建）做融合整理、架构归一（见 §九融合预留）。

---

## 一、这是什么

存量资产之上的**精确变更交付**：外部或自建的 ETL 资产 + 变更需求（新增字段）→ 精确修改 → 回归验证 → 变更制品 → 档案推进。与新建场景（new-pipe：从 RS 到全新资产）并列，共用 designer / coder 两个 agent 岗位与全部设计知识。

**三条红线的落法**：围栏三段机器审计 = 重写不自主；闸口①'/②' + 输出对比人审 = 语义判断不自主；制品只生成 patch 副本不执行 = 推生产不自主。

## 二、总体架构

```
【上游（体系外，责任在供方）】
  逆向侧（dws-analyzer-skill，peer agent）
    └─ /export-baseline → baseline_v1.json（v1.1，文件交接——本体系不调它的脚本）
  业务侧（业务 / 上游 agent）
    └─ RS.md + 已标注 mapping.xlsx（"变更标识"列，格式按我方发布的 mapping-format 规格）

【本体系】
  archives/{schema}/{资产表}/{NNN_日期}/        ← ★唯一锚点：资产档案（入 git，文本小件）
        ▲ 优化交付写回 + 懒归档（首优时从 10_project_deliver 拉入） │ 读（有档零组装）
        │                                                        ▼
  opt-pipe 七步：入口基线 → 输入校验 → designer(ts_v2) → ts围栏 → 闸口①'
                → coder(SQL) → SQL围栏 → ut_opt → 闸口②' → 制品patch → 归档

【下游（体系外）】人/平台执行交付物：ALTER 变更单 / patched 制品副本 / patch 说明——我们不执行
```

**入口三段式查基线**（分岔只在入口，之后完全同构）：
- **档案路径**：`archives/` 有该资产 → 最新目录直接当 baseline（零组装、语义全在、豁免表为空）；
- **懒归档路径**：无档案但 `10_project_deliver/` 有 new-pipe 产出 → 当场 archive_writer 拉一份进档案再用（**建档案的成本只在真正优化时付**；new-pipe 无归档步骤——YAGNI）；
- **json 路径**：都没有 → 收 baseline_v1.json → `assemble_ts_baseline` 入料建档（语义空位 + 自动豁免）。

## 三、流程详解（真实命令，{deliver} = `10_project_deliver/{appid}/{schema}/{资产}/ddlc_opt/`）

### 步骤 0 · 入口与基线
三段式查基线：① `archives/{schema}/{资产表}/` 有档直接用；② 无档但 10_project_deliver 有 new-pipe 产出 → **懒归档**（archive_writer 当场拉档，new-pipe 不做归档步骤）；③ 都没有 → 用户交 baseline_v1.json：

```bash
python SHARED_SCRIPTS/assemble_ts_baseline.py --baseline {baseline_v1.json} --outdir {deliver}/_internal
```
产出四件：`ts_baseline.json` / `etl_baseline/{规则}.sql`（逐字原文）/ `baseline_view.md`（designer 读）/ `exemptions.json`（语义空位清单）。exit 2 = 契约违约（版本/必填/dm=6 缺 merge_on），停线报逆向侧。`kind→load_mode` 词表外的写入类型报"待定"不硬映射。

### 步骤 1 · 输入校验
```bash
python SHARED_SCRIPTS/preprocess_opt.py \
  --mapping {标注mapping.xlsx} --ts-baseline {deliver}/_internal/ts_baseline.json \
  --outdir {deliver}/_internal --rs {RS.md}
```
产出 `change_request.json`（**只装业务说了什么**：字段/含义/源意图/`new_source_table` 信号 + RS 优化章节原文；不含落位）。exit 0/1/2 对齐 precheck 分级：冲突/别名悬空/资产不一致/不支持的标识 = 2 阻断；漏标/RS 未提及 = 1 问人。

### 步骤 2 · designer（优化模式，prompt 显式声明）
dws-designer 加载 **dws-design-opt** skill：读 baseline_view + change_request → 落位决策（opt-playbook 取舍树）→ 新 JOIN 声明 join_safety（强制）→ 回刷判断 → 写增量 decisions（模板 `dws-design-opt/assets/opt-decisions-template.yaml`）→ 组装：

```bash
python DESIGN_SCRIPTS/assemble_ts_opt.py \
  --ts-baseline {deliver}/_internal/ts_baseline.json \
  --decisions {deliver}/_internal/design_decisions_opt.yaml --output {deliver}/ts_v2.json
```
确定性应用（decisions 说的才落、存量一字节不动），产出**完整 ts_v2 + change 段**（下游工具零改造可消费）。

### 步骤 3 · ts 级围栏 → 闸口①'
```bash
python SHARED_SCRIPTS/fence_check.py \
  --ts-baseline {deliver}/_internal/ts_baseline.json --ts-v2 {deliver}/ts_v2.json \
  --change-request {deliver}/_internal/change_request.json
```
**恰好等于双向判定**：diff 的每项必须被声明罩住（越界硬拦：偷加字段/改存量/动冻结槽位/未声明 JOIN…），声明的每条必须有落点（漏改/漏接/夹带硬拦）。过 → **闸口①'三问**（落位确认 / 回刷选择 / 建议追加变更）。

### 步骤 4 · 编码 + SQL 围栏（闸门单点在 pipe）
对 placed_rules 每规则并行发起 coder（dws-coding-opt：以 baseline SQL 为底稿**只加列**，切片带 `--baseline-sql` 与四条硬约束）。全部落盘后 pipe 独立跑：

```bash
python SHARED_SCRIPTS/sql_fence_check.py \
  --ts-v2 {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --baseline-dir {deliver}/_internal/etl_baseline
```
AST 级：老列投影逐列结构等价（**等价改写也拦**）、仅追加声明列、JOIN/WHERE/GROUP BY/CTE 冻结；UNION/SELECT * 显式转人工。

### 步骤 5 · UT（需要数据库；无库跳过）
```bash
python SHARED_SCRIPTS/check_db.py --ts {deliver}/ts_v2.json     # DB_OK / NO_DB_SOURCE
python SHARED_SCRIPTS/ut_opt.py \
  --ts {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --baseline-dir {deliver}/_internal/etl_baseline --ddl-dir {deliver}/ddl \
  --report {deliver}/ut_report_opt.md
```
独立入口（零触碰 ut_precheck/ut_execute）：ALTER 应用（表不存在=环境归人）→ **双向 MINUS 输出对比**（老/新 SELECT 同库同时执行；冻结列差集必须为空）→ INSERT 全量执行（写路径类型转换靠它，两道缺一不可）。主键检查豁免（双跑更强）、空值只查新列。对比失败 → 人定根因：新 JOIN 发散=设计问题回 designer→回闸口①'；源数据=环境归人。

### 步骤 6 · 制品
```bash
python SHARED_SCRIPTS/assemble_ddl_opt.py \
  --ts-v2 {deliver}/ts_v2.json --ts-baseline {deliver}/_internal/ts_baseline.json --outdir {deliver}
python SHARED_SCRIPTS/artifact_patcher.py \
  --ts-v2 {deliver}/ts_v2.json --etl-dir {deliver}/etl \
  --source {原始制品：xlsx 或代码仓规则组目录，按 provenance 定位} \
  --outdir {deliver}/export
```
产出：`ddl/alter_table_{表}.sql`（变更单）+ `ddl_full/`（全量 DDL，档案用，生成后过字段差异审计）+ `export/patched/`（更新后制品**副本**）+ `export/patch_notes.md`。严格 patch：存量声明漂移不碰只报告；xlsx 稳定标识定位+未知列不动；yml round-trip（注释丢失为已知限制）。

### 步骤 7 · 闸口②' → 归档
闸口②'呈现：新列合理性一屏（NULL 率/差集样例）+ 资产健康提示（逆向 warnings 摘要）+ 交付物清单。确认后：

```bash
python SHARED_SCRIPTS/archive_writer.py \
  --ts {deliver}/ts_v2.json --etl-dir {deliver}/etl --ddl-dir {deliver}/ddl_full \
  --decisions {deliver}/_internal/design_decisions_opt.yaml --archives-root archives
```
档案当前态推进（循环链闭合），流程结束。

## 四、核心机制（六件）

1. **档案锚点**：所有资产在体系内只有一个表示。写档案只有两个动作（json 入料 / 懒归档——首优时从标准交付目录拉取；new-pipe 不做归档步骤，YAGNI）；json 出场仅两时机（无档入料、有档供方交 json=声明线上被改→覆盖重入料）；历史=按次目录序列（从首次优化起积累），ts 不含历史。
2. **两级声明**：change_request（业务，脚本产）+ ts.change（落位，designer 声明）——围栏许可 = 合体；落位是设计判断，不是输入的事。
3. **三段审计 + 回路铁律**：意图→落位（fence 内含对账）→结构（fence_check）→代码（sql_fence）。**产物变 → pipe 重跑对应层围栏 → 才进 UT**。
4. **冻结/自由矩阵**：变更声明自带冻结层（逐项等价）/自由层/枚举许可，比对粒度跟冻结层走；第一刀实现 add_field 矩阵，未来类型（modify_field/drop_field/add_source/重构）只加映射不加机制。
5. **输出对比**：双向 MINUS 同数据同时点，oracle 按声明参数化（冻结列零差异、差异只许新列）；与全量 INSERT 互补。
6. **严格 patch**：编辑原语（单元格替换/行追加…）× 变更声明；交付副本模式；存量漂移走变更清单扩充经人，不做 patch 副产品。

## 五、组件清单

**command**：`commands/opt-pipe.md`（编排剧本；编排者铁律沿用 new-pipe）。

**skills**：`dws-design-opt`（薄：增量决策五步 + opt-playbook 落位/回刷决策树 + decisions 模板）、`dws-coding-opt`（薄：底稿加列四步）。references/scripts **不搬家**——路径引用 dws-design / dws-coding 的知识与工具。

**agents**：dws-designer.md / dws-coder.md 各加 opt skill 指针 + `ddlc_opt/` 写权限；岗位/权限/角色认知零改动。

**脚本**（shared 十件中 opt 专属九件 + 纯函数库；dws-design 一件）：

| 脚本 | 职责 | 调用方 |
|------|------|--------|
| baseline_contract.py | 契约校验（schema+版本 1.0/1.1+dm=6 语义） | assemble_ts_baseline / 测试 |
| assemble_ts_baseline.py | json → baseline 包四件 | pipe 步骤 0 |
| preprocess_opt.py | 标注 → change_request + 七项校验 | pipe 步骤 1 |
| assemble_ts_opt.py（dws-design） | 增量 decisions → ts_v2+change 段 | designer |
| fence_check.py | ts 级围栏 | pipe 步骤 3 |
| sql_fence.py / sql_fence_check.py | SQL 围栏（库 + CLI） | pipe 步骤 4（check_sql 自测可选） |
| ut_opt.py | ALTER + 输出对比 + INSERT 全量 | pipe 步骤 5 |
| assemble_ddl_opt.py | ALTER 变更单 + 全量 DDL + 差异审计 | pipe 步骤 6 |
| artifact_patcher.py | xlsx/yml 严格 patch + 副本 + 说明 | pipe 步骤 6 |
| archive_writer.py | 档案写回（NNN 序号；懒归档共用） | opt-pipe 步骤 0/7 |

**契约**：baseline_v1（权威在 analyzer 仓 v1.1；本仓 vendor schema + 校验器；含 write_plan 结构化写入计划——文法翻译非推断）。

## 六、目录约定

```
10_project_deliver/{appid}/{schema}/{资产}/ddlc_opt/     ← 运行时交付目录（gitignore）
├── ts_v2.json / ut_report_opt.md
├── etl/            ← coder 新 SQL（{编号}_{简称}_{写入方式}.sql）
├── ddl/            ← ALTER 变更单（交付）
├── ddl_full/       ← 全量 DDL（档案用）
├── export/         ← patched/ 副本 + patch_notes.md
└── _internal/      ├── baseline_v1.json / ts_baseline.json / etl_baseline/（生产原文，只读）
                    ├── baseline_view.md / exemptions.json / change_request.json
                    ├── design_decisions_opt.yaml └── diagnose/

archives/{schema}/{资产表}/{NNN_日期}/    ← 资产档案（入 git：ts + etl + ddl + decisions）
```

## 七、与新建场景的共享与隔离

**共享**：两个 agent 岗位与权限体系；全部设计知识（references/playbooks）；dws-design/coding 的工具（explore/check_sql 等，路径引用）；precheck 的类型风险交互模式；编排者铁律与闸口纪律。

**隔离（对存量的全部接触只有两处，均加法式）**：agents 各加两行（skill 指针 + opt 目录权限）；slice_ts 加 `--baseline-sql` 参数（不带参数路径逐字节同行为）。**assemble_ts / ut_precheck / ut_execute / assemble_ddl / preprocess 本体零改动**——1001 个测试（含新建全部既有用例）全绿为证。

## 八、测试与验收

- 单测：1001 passed / 2 skipped（不连库；契约 16 + 组装 13 + 预处理 14 + ts 围栏 21 + SQL 围栏 14 + opt 组装 11 + 切片 4 + DDL 6 + UT 5 + patch 4 + 归档 3，及新建全部）；
- 端到端：见 `docs/specs/opt/11-测试指引.md`（输入怎么造 / 每步看什么 / 六个故意踩坑 / 已知限制）；验收三案例（外部全量 / 外部增量+回刷 / 自建档案路径）待实测跑通。

## 九、融合预留（实测后的架构归一）

实测通过后与新建场景归一时的合并点：双 pipe 的入口段统一（资产定位/档案查询成为公共前置）；assemble_ts 与 assemble_ts_opt 的校验/组装函数共享（豁免按位机制接入 N 码）；UT 两入口（ut_precheck+ut_execute / ut_opt）合并为模式分岔的单入口；制品链（assemble_export / artifact_patcher）的编辑原语层共用；AGENTS.md 与 architecture.md 吸收本文。**归一时以本文的实现事实为基准，设计过程的 specs/opt 系列转归档参考。**

## 十、已知限制

1. 回刷窗口老列对比搁置（闸口②'如实提示）；2. `load_mode_pending` 三类 kind（subpartition/rpt_item/exchange）待词表扩展或人工认定；3. yml patch round-trip 丢注释（patch_notes 说明）；4. baseline 语义位空缺 by design（存量不补，双跑兜底）；5. DQ 变更声明位（change.dq）预留未接（DQ 完全跟随输入，第一刀无 DQ 场景）。

## 文档地图

| 文档 | 角色 |
|------|------|
| 本文（architecture/opt-架构设计.md） | **现状手册**：建成事实的单一参考 |
| specs/opt/00-08 | 设计定稿过程（原则/推导/修订史——归一时转参考） |
| specs/opt/09 + 10 | 契约正式版（消费侧）/ 逆向侧实施需求 |
| specs/opt/11-测试指引 | 端到端测试入口 |
| specs/opt/01/02/03… | 各环节设计细节（立场与理由） |
