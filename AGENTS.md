# AGENTS.md — 设计开发 Agent 工作指南

> 新会话先读这个文件 + `CLAUDE.md`（全局认知）+ `commands/new-pipe.md`（唯一编排剧本）。
> 本文件聚焦**当前实际结构**和**容易踩坑的约定**。CLAUDE.md / README.md 部分内容滞后于实际代码，以本文件为准。

---

## 这是什么

数据交付全流程（DDLC）中游段：一个 agent 连续完成「粗设计 → 细设计 → 编码 → UT」。输入 RS（需求 spec），输出 TS 制品包（ts.json/ts.md）+ 四件套制品（DDL/术加 ETL/LTS 调度/DQ）。

三条红线：语义判断不自主（人定）/ 推生产不自主（人推）/ 重写不自主（只精确修改）。

---

## 当前实际结构（以此为准）

```
skills/
├── dws-design/          # 设计 skill（designer agent 用）
│   ├── scripts/         # preprocess.py assemble_ts.py precheck.py gate_summary.py explore.py
│   │                    #   fill_type_risk_decision.py type_compat.py
│   ├── assets/          # ts-template.json design-decisions-template.yaml schedule_config.example.json
│   └── references/      # design-guide.md(物理决策) incremental-playbook.md complexity-playbook.md rs-input-format.md
├── dws-coding/          # 编码 skill（coder agent 用）
│   ├── scripts/         # run_ut.py ut_precheck.py ut_execute.py check_db.py check_sql.py
│   │                    #   assemble_ddl.py assemble_dq.py assemble_export.py slice_ts.py pick_fields.py
│   │                    #   sql_validator.py validate_ddl.py verify_files.py
│   │   └── lib/         # dws_preprocessor.py
│   └── assets/          # db-sources.example.json platform_config.example.json etl-templates.md
└── design-dev-shared/   # ★ 公共代码库（无 SKILL.md，install 单独拷）
    └── scripts/dws_db.py # 连库能力（DBExecutor 抽象 + PsycopgExecutor 实现）
agents/                  # dws-designer.md dws-coder.md（subagent 定义：身份+权限+skill指针+工具清单）
commands/new-pipe.md     # ★ 唯一编排剧本（设计→闸口①→编码→UT→闸口② 全流程）
install.py               # 装 skill/agent/command 到 ~/.config/opencode/
eval-suite/              # 评测套件（v1 + v2，独立工程）
tests/                   # pytest（conftest.py 把三个 scripts 目录加进 sys.path）
10_project_deliver/      # 运行时产出（gitignore，本地重跑覆盖）
docs/                    # architecture/specs/templates/output 示例 + tool-registry.md(★ 工具注册表)
```

### agent 索引

> agent 定义 = 岗位（身份+权限+skill 指针+工具清单）；工作流权威在各自的 SKILL.md，工具详情在 `docs/tool-registry.md`。agent.md 不复述工作流（避免双写漂移）。

| agent | 职责 | skill | 能调的工具（详见 tool-registry.md） | 能写 |
|-------|------|-------|----------------------------------|------|
| **dws-designer** | 设计判断，产 design_decisions.yaml | dws-design | assemble_ts（组装）/ explore（JOIN键唯一性） | `_internal/design_decisions.yaml` |
| **dws-coder** | 单规则 design_logic → SELECT | dws-coding | slice_ts / pick_fields / check_sql | `etl/*.sql`、`dq/*.sql` |

> ★ 其余管线脚本（preprocess / precheck / gate_summary / assemble_ddl / assemble_export / run_ut / ut_* / check_db 等）**调用方都是 command（new-pipe.md 编排）**，不是 agent——它们按"阶段"住在 skill 目录下，但由编排 command 调。权限层两个 agent 都是 `python *` 全放行 + skill 白名单，真正约束 agent 行为的是 **SKILL.md 工作指引**，不是权限。

> 注：`dws-run.py` 在根目录但已不是核心入口，编排走 `commands/new-pipe.md`。

---

## 产出目录约定（★ 关键，常被搞错）

所有产出在 `10_project_deliver/{资产名}/ddlc_design_dev/` 下。**对外产出 vs 过程产物严格分开放**：

```
ddlc_design_dev/
├── ts.json / ts.md      ← 对外（设计产出）
├── etl/                 ← 对外（coder 的 SELECT，R0001.sql）
├── ddl/                 ← 对外（脚本生成的建表 DDL）
├── dq/                  ← 对外（DQ 检查 SQL）
├── ut_report.md         ← 对外（UT 报告，给人看）
├── export/              ← 对外（平台制品包 xlsx，UT 通过后才生成）
└── _internal/           ← ★ 过程产物（验证完就没用，不对外）
    ├── rs_input.json              # 预处理产出（完整，给脚本读）
    ├── rs_input_view.json         # 预处理产出（compact 紧凑视图，给 designer 读）
    ├── design_decisions.yaml      # designer 的设计决策
    ├── ut_precheck_result.json    # UT 预检结果（步骤6a 写，6b 读）
    ├── ut_report.txt              # 执行器内部报告
    ├── ut_sql/                    # UT 执行的实际 SQL 落地（每规则一个文件，debug 用）
    └── diagnose/                  # 数据质量诊断的临时产物
```

**易错点**：
- `ut_precheck_result.json` 放 `_internal/`，**不是** ts.json 同级。ut_precheck.py 默认写这、ut_execute.py 默认读这，且读不到会 **fail loud（退出码2）**，不再静默返回空导致全跳过。
- 临时分析脚本/中间结果统一放 `_internal/diagnose/`，后续提炼成标准脚本。
- 代码默认路径用 `ts_path.parent / "_internal" / "..."`，不要硬编码到 `ts_path.parent` 根下。

---

## 核心流程（new-pipe.md 步骤）

1. **预处理**：preprocess.py 转 rs_input.json（完整，给脚本读；含 schedule.incremental_tables 解析自 RS 增量表段）+ rs_input_view.json（compact 紧凑视图，给 designer 读，省 70%）→ precheck.py 校验输入完整性 + **连库校验字段类型**（pg_catalog UNION ALL 批量查，72h schema 缓存）
   - **`--rs` 可选（无RS模式）**：无 RS 时 mapping 独立驱动核心链路，schedule 用默认值兜底（全量调度/T+1/无增量/无DQ），rs_input 加 `_no_rs_mode` 标记。precheck 给 warn 不阻断。90% 场景建议有 RS（调度/增量/DQ 信息更完整）。
2. **设计**：调 dws-designer 按**五层决策骨架**（SKILL.md §2）思考 → 产 design_decisions.yaml → assemble_ts.py 组装 ts.json + ts.md
   - **五层骨架**：第0层锚点（粒度+主键强制闭合）→ 第1层字段血缘（场景横切）→ 第2层加工路径（step_type/target_role）→ 第3层时间属性（增量逐表对账）→ 第4层工程保障（分布键/调度）。每层有闭合条件，assemble_ts 校验兜底（没过 fail-loud，报错带 `[第X层]` 导航标识）。
   - **TS 校验契约**（assemble_ts.py `run_all_validations`，~38 条）：存量 C7-C13 保留 + 新增 N1-N27。分级：硬阻断（结构不可能对，exit 1）/ 软阻断+豁免（默认拦，填 exemptions 放行，闸口①可见）/ warn。报错按五层分组。
   - **多步骤数据流模型**：每个 rule 有 step_type（full/aggregate/incremental_extract/merge）+ target_role（intermediate/target），多步骤间用 produces_for/reads 声明依赖。**中间表≠聚合**（target_role=intermediate 按"产出供谁消费"定义，可以是 aggregate/full/incremental_extract 任意 step_type）。complexity-playbook §四 是 step_type 决策权威，incremental-playbook 是增量设计权威。
   - **增量防臆想**（攻"只做主表"）：assemble_ts 硬校验 N14（驱动表数≤extract规则数）+ N15/N16。累积共建场景（多来源写同一中间表）标 `build_mode: accumulate`，配 dedup_strategy。
   - designer 可调 explore.py 试算 JOIN 键唯一性（第4层关联安全）。
3. **闸口①**：gate_summary.py 出摘要，人确认设计方向（非交互模式跳过）
4. **DDL**：assemble_ddl.py 从 ts.json 生成建表/视图 DDL
5. **编码**：逐规则调 dws-coder，slice_ts.py 切片单规则上下文，coder 产 SELECT；**DQ 条件化**（ts.dq_rules 非空才调 coder 产 DQ，为空跳过——DQ 完全跟随 RS）
6. **UT**（需数据库）：check_db.py 探活 → 6a ut_precheck（回退+DDL+SELECT预检，秒级）→ 6b ut_execute（INSERT+UT检查，分钟级）
7. **执行回路**（★ 三类分流，见下）
8. **闸口②**：人确认编码质量

### RS vs mapping 职责边界（输入来源归属）

rs_input.json 的信息来自两个输入，职责分明：

**必须从 RS 来的**（mapping 没有）：目标表 schema.table（L1.1）、调度方案/频率/SLA（L07）、增量识别方式+驱动表+增量字段（L07增量表段）、初始化时间范围、湖表调度上游任务、DQ 规则（L06，**完全跟随 RS**：有需求 designer 翻译产 dq_rules、没有不产，取消标准三项系统兜底）、数据探索量级/空值率（L01）、粒度/owner。

**mapping 就够的**（RS 不需要）：源表清单（实体级）、字段映射全部（属性级：源/目标字段名+类型+中文名、映射规则、映射表达式、备注、场景分组）、目标表中文名。**占 rs_input 体积 90%+**。

**两边都有的**：目标表 schema/table（mapping 实体级 + RS L1.1），build_rs_input 的 validate_target_table 做分级校验（都缺=阻断，单边缺/不一致=告警）。

> RS 不稳定的风险集中在元数据段（schema/调度/增量），不影响字段映射主体（mapping 提供，稳定）。预处理对 RS 解析失败有精确报告（段缺失/段在但解析失败/核心字段丢）。

---

---

## UT 失败回路（★ 关键，三类分流）

UT 失败**不要一律回 coder**。按失败项类型分流：

| 类型 | 识别 | 去向 |
|------|------|------|
| **SQL 问题** | INSERT 报错含 COLUMN/TYPE/SYNTAX/DOES NOT EXIST | coder 改语法（**恢复该规则旧会话**，不新开）|
| **数据质量问题** | UT 检查 FAIL：主键重复 / 空值 / 行数异常 | **退回 designer**（绝不给 coder）|
| **环境问题** | 连接/权限/源表不存在/超时 | 闸口②报告给人 |

**数据质量问题为什么不能给 coder**：coder 拿到"主键重复"会用 ROW_NUMBER 去重，掩盖根因（关联发散/关联键选错），反而丢数据。根因在设计层。

**退回 designer 时带"精简依据包"**（够判断即可，别堆数据）：
1. 失败项 + 样例数据（UT 报告现摘；run_ut_check 已加 LIMIT 捕获重复键5个/空值行3行）
2. coder 实际跑的 SELECT 文件路径
3. designer 当初声明的 join_safety + business_key（从 ts.json 摘该规则段）

designer 判断：关联该收敛→改 joins/join_safety；主键标错→改 business_key；源表本身多对一→标"需业务确认"。**改完必须回闸口①人确认**，确认后才恢复 coder 旧会话按新设计改 SELECT。每规则限 3 轮。

---

## 连库（dws_db.py）

`skills/design-dev-shared/scripts/dws_db.py`——设计开发 agent 各 skill 共享。

- **配置**：`~/.config/opencode/db-sources.json`（install 不覆盖已有的；从 `skills/dws-coding/assets/db-sources.example.json` 拷）
- **账号分 role**：`admin`（DDL 建表删表）/ `etl`（SELECT/INSERT 数据读写）。每数据源必配这两个 role。
- **按 schema 选源**：`schema_mapping` 映射 schema→数据源名，找不到回退 default。
- **高层入口**：`create_executor_for_schema(schema, role="etl", config_path="")`——调用方只传 schema+role，不碰配置。低层用 `create_executor(config_path, source, role)`。
- **statement_timeout**：连接建立时按 `security.timeout` 设一次，复用连接都带超时，防 agent kill 进程留僵尸查询。
- **sample_blocks**：`security.sample_blocks`（开发环境配>0 加速 UT，UAT/生产配0）。`resolve_sample_blocks(config_path, cli_value)` 解析：CLI>0 用 CLI，否则读配置，否则0。`inject_tablesample(sql, n)` 用 sqlglot AST 按 JOIN 类型注 TABLESAMPLE SYSTEM(n)：**FROM 主表 + INNER/逗号/CROSS JOIN 表注**（必要表，控制总量），**LEFT/RIGHT/FULL JOIN 从表不注**（外连接侧保留全量，避免切片后关联不上变 NULL），CTE/子查询里的表不注。

**三个 skill 脚本目录都靠相对路径推算 design-dev-shared**：
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
```

---

## 编码约定

- **改工具同步注册表**：加/改/删任何脚本（skills/*/scripts 下的 .py），必须同步更新 `docs/tool-registry.md`（含"读 ts[rules/init]"列——init 下游物化的进度表）。agent 行为/工作流改动同步各自 SKILL.md（唯一源），agent.md 只管角色+权限+指针，不复述工作流（防双写漂移）。
- **禁止 glob 通配匹配文件**（CLAUDE.md 红线）：文件名由生成脚本命名规则确定，查找用确定的文件名拼接（如 `f"create_table_{table}.sql"`）。命名约定变了就改查找代码，不靠通配兜底。
- **测试不连库**：用 Python dict/fake executor 构造数据，`tests/conftest.py` 把三个 scripts 目录加进 sys.path。数据工厂：`make_rs_input`/`make_design_decisions`/`make_ts_json`（基础）+ `make_incremental_rs_input`/`make_incremental_decisions`/`make_accumulate_decisions`（增量/累积共建场景）。`make_design_decisions` 默认产出能通过全部新校验的合法 decisions，测试通过传参注入坏值。
- **Python snake_case**，提交规范 `feat/fix/refactor/docs: 描述`。
- **designer 只改设计不改 SQL**；coder 只接 SQL 语法类问题。职责边界在 agent permission 白名单里硬约束。
- **rs_input 双文件**：`rs_input.json`（field_mappings 行对象列表，assemble_ts/precheck 脚本读）+ `rs_input_view.json`（compact 分块紧凑视图，designer 读）。同一次 preprocess 产出（view 是 build_compact 从 input 派生），天然一致。designer 用 Read 读 view（23KB）而非 input 全文（120KB）。
- **ts 多步骤数据流模型**：rule 有 step_type（full 单规则直灌/装配/非聚合中间加工 / aggregate 聚合产出 / incremental_extract 增量取数到 tmp / merge 合并 tmp 到目标）+ target_role（intermediate/target）。中间表和目标表可有同名字段（按 (表,字段) 查重，不按全局）。多步骤依赖用 produces_for/reads 声明（与 data_flow.dependencies 互补），assemble_ts 校验依赖闭合（N9-N12：produces_for 非空、reads 非空、双向对账 N10b、依赖顺序 N10c、循环检测 N10d）。简单全量走 full 老路不受影响。**中间表≠聚合**，step_type 决策权威是 complexity-playbook §四。
- **累积共建模式**（多来源写同一中间表，常见于去重/union 场景）：中间表标 `tables.{表}.build_mode: accumulate`，同表字段可重叠（C9 在 accumulate 模式放行）。排重策略由 designer 定（rule 级 `dedup_strategy`：key/priority/reason），coder 翻译成 SQL。详见 incremental-playbook §三/§四。
- **TS 校验契约分级**（assemble_ts.py）：硬阻断（N1-N4 锚点 / N5 加工字段必写 logic / N6-N12 路径 / N14-N15 增量 / N18-N21 工程 / N22 参数 / N25 design_approach / N_INIT2 增量目标禁 truncate / N_INIT1 init 规则禁手填 load_mode / N_INIT_MODE·N_INIT_GROUP 合法值）/ 软阻断（N16-N17 增量合并，填 exemptions 放行）/ warn（N23-N24/N27/N_INIT3 delta机器残留/N_INIT4 init口径空）。分层：L0-L4/LC/LA/LD/**LI(初始化设计)**。完整契约见 assemble_ts.py 的 `run_all_validations` + `ValidationResult`。
- **写入配置（load_mode + write_condition）**：coder 只写 SELECT，写入动作（INSERT/MERGE/PARTITION/DELETE）由平台配置 + run_ut 拼接。rule 有 write_condition（对应平台 delete_condition）：merge_into/update 填 ON 条件如 `T.id=T1.id`（T=目标表别名 T1=源）；truncate_partition 填分区名如 `P_1001`；delete 填删除 WHERE；truncate_table/no_delete 留空。**统一 designer 填不做推导**（assemble_ts 校验非空+非中文）。run_ut 的 wrap_write 按 load_mode 拼：非 merge 走 INSERT，merge_into/update 拼 MERGE INTO...USING...ON...WHEN MATCHED/NOT MATCHED。assemble_export 的删除模式从 load_mode 映射（不再硬编码"1"）。
- **init 双管道模型**（★ 增量资产的核心结构）：init 和增量是**同一目标表的两个写入管道**——增量管道（`rules`）日常跑（load_mode=merge_into/no_delete/...），init 管道（`init` 段）首次全量装载（load_mode 恒为 truncate_table 先删全插）。一个 rule 一个 load_mode 装不下两者，故 init 单独成段。**增量目标规则禁用 truncate_table**（N_INIT2 硬阻断，全删全插会清空历史）。两种 mode：**derive**（增量无 delta 机器，init 从增量+init_filter 派生，designer 不写 init 规则）/ **explicit**（增量有 delta 机器，init 独立设计，designer 写 core_from+joins，装配器按 7 不变量补 target/load_mode/field_targets）。group_mode：inline（同组 p_flag）/ separate（独立规则组）。装配器 `build_init_section` 幂等（main 校验阶段也调）。详见 incremental-playbook §八。本轮做设计侧（ts.json init 段 + 装配器 + LI 校验 + ts.md），下游物化（execution_tasks/SQL/调度）后续 chunk。

## 开发命令

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v          # 全量测试（当前 465 个）
python3 -m pytest tests/test_assemble_ts.py::TestLayer3Incremental -v  # 跑某层校验
python install.py                    # 全局安装 skill/agent/command 到 ~/.config/opencode/
```

> 本环境 `python` 不可用，用 `python3`。

## 关键文档

- `commands/new-pipe.md`——★ 唯一编排剧本（改流程先读这个）
- `skills/dws-design/SKILL.md`——★ **五层决策骨架**（designer 思考主线，改设计流程先读这个）
- `skills/dws-design/references/incremental-playbook.md`——增量设计全集（数据流/累积共建/排重/初始化/豁免）
- `skills/dws-design/references/complexity-playbook.md`——复杂度评估 + CTE/物化决策 + step_type 决策树
- `skills/dws-design/references/design-guide.md`——物理设计决策（分布键/分区）+ 依赖类型（精简版）
- `skills/dws-design/assets/ts-template.json`——ts.json 权威结构定义
- `skills/dws-design/assets/design-decisions-template.yaml`——designer 产出格式（含 build_mode/dedup_strategy/data_volume/exemptions）
- `docs/architecture/architecture.md`——架构（环境/四区/决策记录）
- `eval-suite/idle-task-prompt.md`——闲时任务（试算SQL/调度路径/测试覆盖）

## 已知滞后项

`CLAUDE.md` 和 `README.md` 仍描述旧的 `dws-pipeline-*` 9-skill 结构，与实际不符。实际是 `dws-design` + `dws-coding` + `design-dev-shared` 三个 skill + 两个 agent（designer/coder）+ 一个 command（new-pipe）。改这两个文件时以本 AGENTS.md 和实际代码为准。

> CLAUDE.md 的"全局认知/架构共识/历史推理"部分仍有参考价值，但涉及**当前实际结构、设计流程、校验契约**的内容以本 AGENTS.md 为准（CLAUDE.md 不再同步细节改动）。

### 本轮改造（设计思维重构 + TS 校验契约补强，2026-08）

design-guide.md 已从 335 行大杂烩拆分为：design-guide（物理决策，70行）+ incremental-playbook（增量全集）+ complexity-playbook（复杂度/物化/step_type）。SKILL.md 的 9 步操作清单已重构为**五层决策骨架**。assemble_ts.py 新增 `run_all_validations`（~38 条校验，五层分组）+ `ValidationResult`（分层报错）+ 软阻断豁免机制。design_decisions 模板补 `build_mode`/`dedup_strategy`/`data_volume`/`exemptions`。preprocess.py 内嵌的死代码 precheck 副本已删除。测试 419→465。

### init 双管道模型改造（2026-08）

修掉增量场景的致命 bug：增量目标 load_mode=truncate_table 导致每次增量全删全插。根因是一个 rule 一个 load_mode 装不下 init/增量两种写入。改为**双管道模型**：增量管道（`rules`，load_mode=merge 等）+ init 管道（`init` 段，load_mode 恒 truncate_table）。新增 LI 层校验（N_INIT1/2/3/4 + mode/group_mode 合法值）+ `build_init_section` 装配器（7 不变量补全 + core_from 抄口径，幂等）。两种 mode：derive（无 delta 机器，派生）/ explicit（有 delta 机器，独立设计）。group_mode：inline（同组 p_flag）/ separate（独立规则组）。incremental-playbook §八 重写。本轮做**设计侧**（ts.json init 段 + 装配器 + LI 校验 + ts.md + 测试），下游物化（execution_tasks/init SQL/调度任务）后续 chunk。ts.md §8 不再按 load_mode 藏增量规则。测试 +21。

### DQ RS 驱动改造（2026-08）

DQ 产出从"designer 随机决定"改为"**完全跟随 RS**"，消除"一次有一次没有"的不稳定。核心：
- **DQ 100% 跟随 RS**：`rs_input.dq_requirements` 非空 → designer 翻译产 `dq_rules`；为空 → `dq_rules` 留空。
- **designer 是翻译者**（不是搬运工，类比 field_logics 写 design_logic）：scope/check_type/rule_name 跟 RS 一致，rule_desc 写技术口径给 coder。
- **取消"标准三项"系统兜底**（主键唯一/审计非空/记录数不再无条件产）。
- assemble_ts 新增 LD 层校验：N_DQ1（硬阻断，RS 有 DQ 但 dq_rules 空）/ N_DQ2（warn，条数偏少）/ N_DQ3（warn，RS 无但自加）。
- DQ 调度任务条件化（dq_rules 空不建 tasks["dq"]）；coder 条件化调用（dq_rules 空不调）。
- preprocess build_compact 加 `dq` 段（designer 读 view 就看到 RS 的 DQ 需求）。
- assemble_dq.py（废弃脚本）不改逻辑仅供 eval 复现，文件头注释说明与生产路径不一致。
