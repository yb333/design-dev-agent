---
status: active
last_reviewed: 2026-09-01
depends_on: [../specs/opt/00-总纲与范围.md]
edition: 实现版 v3（2026-09-01 目录定调重写：档案=ddlc_design_dev/archive/ 单目录当前态、分拣器退役、
资产标识铆定 I；设计过程版见 git 历史与 specs/opt 系列）
---

# 优化场景架构与操作手册（opt，实现版）

> 本文是优化场景的**单一现状参考**：架构、流程（含真实命令）、组件清单、目录约定、机制说明——全部以已建成并通过测试的代码为准。设计推演过程与原则全文在 `docs/specs/opt/00-08`；端到端测试入口在 `11-测试指引`。
> **定位**：实测优化场景期间的权威手册；实测通过后与 `architecture.md`（新建）做融合整理、架构归一（见 §九融合预留）。

---

## 一、这是什么

存量资产之上的**精确变更交付**：外部或自建的 ETL 资产 + 变更需求（新增字段）→ 精确修改 → 回归验证 → 变更制品 → 档案推进。与新建场景（new-pipe：从 RS 到全新资产）并列，共用 designer / coder 两个 agent 岗位与全部设计知识。

**三条红线的落法**：围栏三段机器审计 = 重写不自主；闸口①'/②' + 输出对比人审 = 语义判断不自主；制品只生成 patch 副本不执行 = 推生产不自主。

## 二、总体架构（2026-09-01 目录定调）

**基石**：资产标识 = mapping 声明的目标表（**铆定 I 视图**——业务身份；只存 F 不对外消费的资产即 F 名，按人写的算）。档案 = `ddlc_design_dev/archive/` **当前态唯一真身**，入 git，演进史 = git 提交历史（每次交付覆盖 + 一次 commit，NNN 序列退役）。

```
【上游（体系外，责任在供方）】
  逆向侧（dws-analyzer-skill，peer agent）→ baseline_v1.json（v1.1，文件交接——不调它的脚本）
  业务侧 → 全量 mapping（备注"{YYYYMM}版本{动词}"标记变更）+ RS（3.3 变更记录 + 版本锚定段）
          —— 都是契约参数直传（--mapping/--rs 文件路径），分拣器已退役（脚本不猜输入）

【本体系】 10_project_deliver/{appid}/{schema}/{资产=I名}/ddlc_design_dev/
  archive/          ← 资产档案（入 git）：ts.json/ts.md/etl/{rule}.sql/ddl//dq//decisions.yaml
  opt/              ← 本次优化更新（每次开工重建；gitignore）：ts_v2 + 新 SQL + ALTER + patch + 过程件
  （平铺产物/export/_internal ← new-pipe 建造的交付现场，首优收档后留原位）

  opt-pipe 七步：入口基线 → 输入校验 → designer(ts_v2) → ts围栏 → 闸口①'
                → coder(SQL) → SQL围栏 → DDL变更单 → ut_opt → 闸口②' → 制品patch → 档案推进

【下游（体系外）】人/平台执行交付物：ALTER 变更单 / patched 制品副本 / patch 说明——我们不执行
```

**入口三段式查基线**（分岔只在入口，之后完全同构）：
- **有档案**：`archive/ts.json` 存在 → 直接当 baseline（脚本只读直读，无快照拷贝；写坏有 git 兜底）；
- **首优收档**：无档案但 ddlc_design_dev 有平铺 new-pipe 产出 → `archive_writer adopt` 原地收纳（mv ts/etl/ddl/dq + cp decisions）→ git 首次提交 = 建档。new-pipe 平铺产出零改动（不为不确定的优化预付结构成本）；
- **json 入料**：都没有 → baseline_v1.json 契约校验 → 组装（档案件落 archive/、过程件落 opt/_internal/）= 建档。

**回归能力**：确认前档案零改动（所有工作产物只进 opt/）——放弃优化 = 扔掉 opt/ 现场，档案无损；确认后推进（覆盖+commit），反悔 = git revert。数据库层回归（ALTER 已应用）第一刀不承诺（开发库重建），闸口②'如实提示。

## 三、流程详解（真实命令；{ddlc}=ddlc_design_dev，{arc}={ddlc}/archive，{opt}={ddlc}/opt）

### 步骤 0 · 入口与基线
`preprocess.py --probe` 定位资产 → 三段式查基线（见 §二）。json 入料：

```bash
python PIPE_SCRIPTS/assemble_ts_baseline.py \
  --baseline {baseline_v1.json} --archive-dir {arc} --internal-dir {opt}/_internal
```
档案件（ts.json + etl/{rule}.sql 逐字原文）落 `{arc}`；过程件（baseline_view.md + exemptions.json）落 `{opt}/_internal`。provenance（原始制品定位）落 `ts._baseline.provenance`。exit 2 = 契约违约（版本/必填/dm=6 缺 merge_on），停线报逆向侧。`kind→load_mode` 词表外的写入类型报"待定"不硬映射。首优收档：`archive_writer adopt --ddlc {ddlc}`。

### 步骤 1 · 优化输入预处理（契约参数直传；输入文件禁止 Read）
```bash
python PIPE_SCRIPTS/preprocess_opt.py \
  --mapping {mapping.xlsx} --rs {RS.md} \
  --ts-baseline {arc}/ts.json --outdir {opt}/_internal [--version 202608]
```
版本锚点（RS 变更记录最新"优化"行日期归一 YYYYMM）→ 备注标记提取（属性级新增=字段候选、实体级新增=新来源；其他动词识别归类报告"待扩展"）→ 校验（冲突/别名悬空/**资产一致[I/F 镜像归一比基名]**/版本定位；漏标/RS 未提及 warn）→ `change_request.json`（只装业务说了什么；闸口①'把简述↔提取字段并排供人扫漏标）。exit 0/1/2 对齐 precheck 分级。

### 步骤 2 · designer（优化模式，prompt 显式声明）
dws-designer 加载 **dws-design-opt** skill：读 `{opt}/_internal/baseline_view.md` + `change_request.json` → 落位决策（opt-playbook 取舍树）→ 新 JOIN 声明 join_safety（强制）→ 回刷判断 → 写增量 decisions → 组装：

```bash
python DESIGN_SCRIPTS/assemble_ts_opt.py \
  --ts-baseline {arc}/ts.json \
  --decisions {opt}/_internal/design_decisions_opt.yaml --output {opt}/ts_v2.json
```
确定性应用（decisions 说的才落、存量一字节不动），产出**完整 ts_v2 + ts.md + change 段**（下游工具零改造可消费；_baseline 含 provenance 深拷贝透传）。

### 步骤 3 · ts 级围栏 → 闸口①'
```bash
python PIPE_SCRIPTS/fence_check.py \
  --ts-baseline {arc}/ts.json --ts-v2 {opt}/ts_v2.json \
  --change-request {opt}/_internal/change_request.json
```
**恰好等于双向判定**：diff 的每项必须被声明罩住（越界硬拦：偷加字段/改存量/动冻结槽位/未声明 JOIN…），声明的每条必须有落点（漏改/漏接/夹带硬拦）。过 → **闸口①'三问**（落位确认 / 回刷选择 / 建议追加变更；options 必含"退 BA"一等选项）。

### 步骤 4 · 编码 + SQL 围栏（闸门单点在 pipe）
对 placed_rules 每规则并行发起 coder（dws-coding-opt：以 baseline SQL 为底稿**只加列**，切片带 `--baseline-sql {arc}/etl/{rule}.sql`——档案只读）。**落盘名 = {rule_code}.sql 与档案同名**（一个规则一个文件，新 SQL 即该规则当前版）。全部落盘后 pipe 独立跑：

```bash
python PIPE_SCRIPTS/sql_fence_check.py \
  --ts-v2 {opt}/ts_v2.json --etl-dir {opt}/etl --baseline-dir {arc}/etl
```
AST 级：老列投影逐列结构等价（**等价改写也拦**）、仅追加声明列、JOIN/WHERE/GROUP BY/CTE 冻结；UNION/SELECT * 显式转人工。

### 步骤 5 · DDL 变更单 → UT（需要数据库；无库跳过）
**先产 ALTER 变更单**（ut_opt 依赖它应用新列；缺失 fail loud exit 2——2026-09-01 修正，不再静默跳过错分 coder）：

```bash
python PIPE_SCRIPTS/assemble_ddl_opt.py \
  --ts-v2 {opt}/ts_v2.json --ts-baseline {arc}/ts.json --outdir {opt}
python SHARED_SCRIPTS/check_db.py --ts {opt}/ts_v2.json     # DB_OK / NO_DB_SOURCE
python PIPE_SCRIPTS/ut_opt.py \
  --ts {opt}/ts_v2.json --etl-dir {opt}/etl \
  --baseline-dir {arc}/etl --ddl-dir {opt}/ddl --report {opt}/ut_report_opt.md
```
独立入口（零触碰 ut_precheck/ut_execute）：ALTER 应用（表不存在=环境归人）→ **双向 MINUS 输出对比**（老/新 SELECT 同库同时执行；冻结列差集必须为空）→ INSERT 全量执行。主键检查豁免（双跑更强）、空值只查新列。对比失败 → 人定根因：新 JOIN 发散=设计问题回 designer→回闸口①'；源数据=环境归人。

### 步骤 6 · 制品
```bash
python PIPE_SCRIPTS/artifact_patcher.py \
  --ts-v2 {opt}/ts_v2.json --etl-dir {opt}/etl \
  --source {原始制品：xlsx 或代码仓规则组目录} --outdir {opt}/export
```
`--source` 定位顺序：`ts_v2._baseline.provenance` → 取不到问人。产出：`{opt}/ddl/alter_table_{表}.sql`（变更单）+ `{opt}/ddl_full/`（推进材料）+ `{opt}/export/patched/`（更新后制品**副本**）+ `patch_notes.md`。严格 patch：存量声明漂移不碰只报告；xlsx 稳定标识定位+未知列不动；yml round-trip（注释丢失为已知限制）。

### 步骤 7 · 闸口②' → 档案推进
闸口②'呈现：新列合理性一屏（NULL 率/差集样例）+ 资产健康提示（逆向 warnings 摘要）+ 交付物清单。确认后**交付收口**：

```bash
python PIPE_SCRIPTS/archive_writer.py advance --opt {opt} --archive {arc}
```
ts_v2/ts.md/新 SQL（同名覆盖=规则当前版）/ddl_full/decisions_opt → 档案当前态推进；opt/ 现场保留（交付物人取用），下次优化开工重建。然后 `git add {arc} && git commit`（message 记变更摘要）。流程结束，人拿交付物去执行（推生产不自主）。

## 四、核心机制（六件）

1. **档案锚点**：资产当前态唯一真身 = `ddlc_design_dev/archive/`（ts/etl/ddl/dq/decisions）。建档三时机（首优收档 / json 入料 / 交付收口推进）；演进史 = git 提交历史；json 出场仅两时机（无档入料、有档供方交 json=声明线上被改→覆盖重入料）。
2. **两级声明**：change_request（业务，脚本产）+ ts.change（落位，designer 声明）——围栏许可 = 合体；落位是设计判断，不是输入的事。
3. **三段审计 + 回路铁律**：意图→落位（fence 内含对账）→结构（fence_check）→代码（sql_fence）。**产物变 → pipe 重跑对应层围栏 → 才进 UT**。
4. **冻结/自由矩阵**：变更声明自带冻结层（逐项等价）/自由层/枚举许可，比对粒度跟冻结层走；第一刀实现 add_field 矩阵，未来类型（modify_field/drop_field/add_source/重构）只加映射不加机制。
5. **输出对比**：双向 MINUS 同数据同时点，oracle 按声明参数化（冻结列零差异、差异只许新列）；与全量 INSERT 互补。
6. **严格 patch**：编辑原语（单元格替换/行追加…）× 变更声明；交付副本模式；存量漂移走变更清单扩充经人，不做 patch 副产品。

## 五、组件清单

**command**：`commands/opt-pipe.md`（薄壳入口：frontmatter agent 路由 + 加载 opt-pipe skill；生产走 Task 直连 dws-engineer）。

**skills**：`opt-pipe`（编排剧本）、`dws-design-opt`（薄：增量决策五步 + opt-playbook 落位/回刷决策树 + decisions 模板）、`dws-coding-opt`（薄：底稿加列四步）。references/scripts **不搬家**——设计知识与工具路径引用 dws-design / dws-coding。

**agents**：dws-designer.md / dws-coder.md 各加 opt skill 指针 + `ddlc_design_dev/opt/` 写权限；岗位/权限/角色认知零改动。

**脚本**（全住 `skills/opt-pipe/scripts`（含 schemas/baseline_v1.schema.json）；assemble_ts_opt 在 dws-design）：

| 脚本 | 职责 | 调用方 |
|------|------|--------|
| baseline_contract.py | 契约校验（schema+版本 1.0/1.1+dm=6 语义） | assemble_ts_baseline / 测试 |
| assemble_ts_baseline.py | json 入料建档（档案件→archive/，过程件→opt/_internal/；provenance 落 ts） | opt-pipe 步骤 0 |
| preprocess_opt.py | 标注 → change_request + 校验（--mapping/--rs 直传；I/F 镜像归一） | opt-pipe 步骤 1 |
| assemble_ts_opt.py（dws-design） | 增量 decisions → ts_v2 + ts.md + change 段 | designer |
| fence_check.py | ts 级围栏 | opt-pipe 步骤 3 |
| sql_fence.py / sql_fence_check.py | SQL 围栏（库 + CLI） | opt-pipe 步骤 4 |
| ut_opt.py | ALTER（缺失 fail loud）+ 输出对比 + INSERT 全量 | opt-pipe 步骤 5 |
| assemble_ddl_opt.py | ALTER 变更单 + 全量 DDL + 差异审计 | opt-pipe 步骤 5（先于 UT） |
| artifact_patcher.py | xlsx/yml 严格 patch + 副本 + 说明（--source 按 provenance 定位） | opt-pipe 步骤 6 |
| archive_writer.py | 档案两动作：adopt 首优收档 / advance 交付收口推进 | opt-pipe 步骤 0/7 |

**契约**：baseline_v1（权威在 analyzer 仓 v1.1；本仓 vendor schema + 校验器；含 write_plan 结构化写入计划——文法翻译非推断）。

## 六、目录约定（2026-09-01 定调）

```
10_project_deliver/{appid}/{schema}/{资产=I名}/ddlc_design_dev/     ← 段产出统一根（gitignore，archive/ 白名单入 git）
├── archive/         ← ★资产档案=当前态唯一真身：ts.json/ts.md/etl/{rule}.sql/ddl//dq//decisions.yaml
│                       （目录承载版本已退役——演进史=git 提交历史；文件名承载角色恒定）
├── （ts.json/etl/… export/ _internal/ ← new-pipe 平铺产出与交付现场；首优收档后 ts/etl/ddl/dq 移入 archive/ 留档）
└── opt/             ← 本次优化更新（每次开工重建）
    ├── ts_v2.json / ts.md / etl/（{rule_code}.sql 与档案同名）/ ddl/（ALTER 变更单）
    ├── ddl_full/（全量 DDL 推进材料）/ export/（patched/ + patch_notes.md）/ ut_report_opt.md
    └── _internal/（baseline_v1.json / baseline_view.md / exemptions.json / change_request.json
                    / design_decisions_opt.yaml / diagnose/）
```

## 七、与新建场景的共享与隔离

**共享**：两个 agent 岗位与权限体系；全部设计知识（references/playbooks）；dws-design/coding 的工具（explore/check_sql 等，路径引用）；precheck 的类型风险交互模式；编排者铁律与闸口纪律；check_env 探针（opt-pipe 跨剧本引用 new-pipe/scripts，先例 dws-dq 借 slice_ts）。

**隔离（对存量的全部接触只有两处，均加法式）**：agents 各加两行（skill 指针 + opt 目录权限）；slice_ts 加 `--baseline-sql` 参数（不带参数路径逐字节同行为）。**assemble_ts / ut_precheck / ut_execute / assemble_ddl / preprocess 本体零改动**——全量测试全绿为证。

## 八、测试与验收

- 单测：全量套件（不连库；契约 + 组装 + 预处理[含 I/F 归一/直传] + ts 围栏 + SQL 围栏 + opt 组装[含 ts.md] + UT[含 ALTER 缺失 fail loud] + patch + 档案两动作[adopt/advance]）；
- 端到端：见 `docs/specs/opt/11-测试指引.md`（注意：该文档写于目录定调前，命令路径/目录形态以本文与 opt-pipe SKILL 为准，待实测后一并刷新）；验收三案例（外部全量 / 外部增量+回刷 / 自建档案路径）待实测跑通。

## 九、融合预留（实测后的架构归一）

实测通过后与新建场景归一时的合并点：双 pipe 的入口段统一（资产定位/档案查询成为公共前置）；assemble_ts 与 assemble_ts_opt 的校验/组装函数共享（豁免按位机制接入 N 码）；UT 两入口（ut_precheck+ut_execute / ut_opt）合并为模式分岔的单入口；制品链（assemble_export / artifact_patcher）的编辑原语层共用；AGENTS.md 与 architecture.md 吸收本文。**归一时以本文的实现事实为基准，设计过程的 specs/opt 系列转归档参考。**

## 十、已知限制

1. 回刷窗口老列对比搁置（闸口②'如实提示；backfill 仅记录意向，无回刷脚本产出）；2. `load_mode_pending` 三类 kind（subpartition/rpt_item/exchange）待词表扩展或人工认定；3. yml patch round-trip 丢注释（patch_notes 说明）；4. baseline 语义位空缺 by design（存量不补，双跑兜底）；5. DQ 变更声明位（change.dq）预留未接（第一刀无 DQ 场景）；6. sync_to_team 对 deliver 深处 archive/ 的同步待内网验证。

## 文档地图

| 文档 | 角色 |
|------|------|
| 本文（architecture/opt-架构设计.md） | **现状手册**：建成事实的单一参考 |
| specs/opt/00-08 | 设计定稿过程（原则/推导/修订史——归一时转参考） |
| specs/opt/09 + 10 | 契约正式版（消费侧）/ 逆向侧实施需求 |
| specs/opt/11-测试指引 | 端到端测试入口（目录定调前所写，命令以 opt-pipe SKILL 为准） |
