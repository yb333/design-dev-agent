# AGENTS.md — 设计开发 Agent 工作指南

> 新会话先读这个文件 + `CLAUDE.md`（全局认知）+ `skills/new-pipe/SKILL.md`（新建编排剧本，唯一源）+ `docs/integration-contract.md`（总控对接契约）。
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
│   ├── scripts/         # assemble_ts.py assemble_ts_opt.py(opt侧用) explore.py check_field.py(字段查证,designer自有入口) pick_targets.py(字段清单取料,designer自有入口) fill_type_risk_decision.py fill_join_risk_decision.py
│   ├── assets/          # ts-template.json design-decisions-template.yaml schedule_config.example.json schema_apps.example.json
│   └── references/      # design-guide.md(物理决策) incremental-playbook.md complexity-playbook.md rs-input-format.md
├── dws-coding/          # 编码 skill（coder agent 用）
│   ├── scripts/         # check_sql.py slice_ts.py pick_fields.py（视图=F表配套镜像非规则，is_view_step 概念已清除）
│   └── assets/          # db-sources.example.json platform_config.example.json etl-templates.md
├── dws-dq/              # DQ 检查 SQL 生成 skill（coder agent 的 DQ 任务用，薄——仅 SKILL.md 定契约，工具复用 dws-coding 的 slice_ts --dq / check_sql）
├── new-pipe/            # ★ 新建编排剧本 skill（dws-engineer 加载执行：预处理→设计→闸口①→编码→UT→闸口②→制品）
│   └── scripts/         # check_env.py(步骤0环境探针:安装指纹/关键文件/python版本)
├── opt-pipe/            # ★ 优化编排剧本 skill（dws-engineer 加载执行：基线→增量设计→围栏→SQL围栏→UT→制品patch→归档）
└── design-dev-shared/   # ★ 公共代码库 + pipe 管线脚本（纯代码库无 SKILL.md——路径锚点职能已由 new-pipe/opt-pipe 的 Base directory 承接，install 单独拷）
    └── scripts/         # dws_db.py(连库) config_paths.py(★config路径集中) resolve_appid.py(查appid)
                         #   dispatch_plan.py schema_query.py
                         #   ★ pipe 调的管线脚本（2026-08 按调用方归位）：
                         #   preprocess.py precheck.py gate_summary.py（原 dws-design）
                         #   assemble_ddl.py assemble_export.py ut_precheck.py ut_execute.py check_db.py（原 dws-coding）
                         #   ★ 被 shared 消费的函数库（2026-08 下沉，消 shared↔skill 依赖环）：
                         #   run_ut.py(UT函数库,无main) ut_diagnose.py(类型诊断) type_compat.py(类型兼容)
                         #   sql_parse.py(SQL文本解析原语) dws_standards.py(审计字段标准常量) ts_compat.py(ts结构兼容:分桶原语+旧结构升级)
                         #   ★ opt-pipe 调的（对存量零接触，详见 tool-registry ⑤）：
                         #   preprocess_opt.py fence_check.py sql_fence.py sql_fence_check.py ut_opt.py
                         #   assemble_ddl_opt.py assemble_ts_baseline.py artifact_patcher.py
                         #   archive_writer.py baseline_contract.py
                         #   ★ 分层铁律：shared 只 import shared + 标准库/三方库，绝不 import dws-design/dws-coding；
                         #     design/coding 只能向下 import shared（箭头单向）
agents/                  # dws-engineer.md(编排:身份+权限+契约参数+铁律) dws-designer.md dws-coder.md（subagent 定义：身份+权限+skill指针+工具清单）
commands/new-pipe.md     # 薄壳入口（frontmatter agent: dws-engineer + 一行加载 new-pipe skill——人手工 /new-pipe 用；生产走 Task 直连）
commands/opt-pipe.md     # 薄壳入口（同上，加载 opt-pipe skill）
skills/dws-design-opt/   # 优化设计 skill（薄：读 baseline_view+change_request→增量 decisions→assemble_ts_opt）
skills/dws-coding-opt/   # 优化编码 skill（薄：以 baseline SQL 为底稿加列，老列不动）
archives/                # ★ 资产档案（唯一锚点：{schema}/{资产}/{NNN_日期}/，文本小件入 git）
install.py               # 装 skill/agent/command 到 ~/.config/opencode/
eval-suite/              # 评测套件（v1 + v2，独立工程；eval.sh/eval.bat 交互式菜单入口）
tests/                   # pytest（conftest.py 把三个 scripts 目录加进 sys.path）
10_project_deliver/      # 运行时产出（gitignore，本地重跑覆盖）
docs/                    # architecture/specs/templates/output 示例 + tool-registry.md(★ 工具注册表)
```

### agent 索引

> agent 定义 = 岗位（身份+权限+skill 指针+工具清单）；工作流权威在各自的 SKILL.md，工具详情在 `docs/tool-registry.md`。agent.md 不复述工作流（避免双写漂移）。

| agent | 职责 | skill | 能调的工具（详见 tool-registry.md） | 能写 |
|-------|------|-------|----------------------------------|------|
| **dws-engineer** | 设计开发段编排：契约参数→加载剧本→调管线脚本→起 designer/coder→守闸口 | new-pipe / opt-pipe（按模式路由） | check_env（步骤0探针）；管线脚本经 bash python 调（不属 agent 工具） | `ddlc_design_dev/**`、`ddlc_opt/**` |
| **dws-designer** | 设计判断，产 design_decisions.yaml | dws-design / dws-design-opt（按任务路由） | assemble_ts（组装）/ assemble_ts_opt（opt 组装）/ explore（JOIN键唯一性）/ check_field（字段查证）/ pick_targets（字段清单取料） | `_internal/design_decisions.yaml` |
| **dws-coder** | 单规则 SELECT + DQ 检查 SQL | dws-coding / dws-dq / dws-coding-opt（按任务路由） | slice_ts（含 --dq）/ pick_fields / check_sql | `etl/*.sql`、`dq/*.sql` |

> ★ 其余管线脚本（preprocess / precheck / gate_summary / assemble_ddl / assemble_export / run_ut / ut_* / check_db 等）**调用方都是 command（new-pipe.md 编排）**，不是 agent——它们统一住在 `design-dev-shared/scripts`（2026-08 按调用方归位）。权限层两个 agent 都是 `python *` 全放行 + skill 白名单，真正约束 agent 行为的是 **SKILL.md 工作指引**，不是权限。

> 注：`dws-run.py` 在根目录但已不是核心入口，编排走 dws-engineer（剧本 skills/new-pipe/SKILL.md，入口 Task 直连或 /new-pipe 薄壳）；根目录另有 `sync_to_team.py/.sh/.bat` + `SYNC-GUIDE.md`（本仓→内网仓同步工具，用户手工操作，与 pipe 无关）。

---

## 产出目录约定（★ 关键，常被搞错）

所有产出在 `10_project_deliver/{appid}/{schema}/{资产名}/ddlc_design_dev/` 下（appid/schema 两层按 schema 从 schema_apps.json 查；resolve_appid.py 查 appid）。**对外产出 vs 过程产物严格分开放**：

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

## 核心流程（new-pipe 剧本步骤，skills/new-pipe/SKILL.md）

1. **预处理**：preprocess.py 转 rs_input.json（完整，给脚本读；含 schedule.incremental_tables 解析自 RS 增量表段）+ rs_input_view.json（compact 紧凑视图，给 designer 读，省 70%）→ precheck.py 校验输入完整性 + **连库校验字段类型**（pg_catalog UNION ALL 批量查，24h schema 缓存）
   - **`--rs` 可选（无RS模式）**：无 RS 时 mapping 独立驱动核心链路，schedule 用默认值兜底（全量调度/T+1/无增量/无DQ），rs_input 加 `_no_rs_mode` 标记。precheck 给 warn 不阻断。90% 场景建议有 RS（调度/增量/DQ 信息更完整）。
2. **设计**：调 dws-designer 按**五层决策骨架**（SKILL.md §2）思考 → 产 design_decisions.yaml → assemble_ts.py 组装 ts.json + ts.md
   - **五层骨架**：第0层锚点（粒度+主键强制闭合）→ 第1层字段血缘（场景横切）→ 第2层加工路径（step_type/target_role）→ 第3层时间属性（增量逐表对账）→ 第4层工程保障（分布键/调度）。每层有闭合条件，assemble_ts 校验兜底（没过 fail-loud，报错带 `[第X层]` 导航标识）。
   - **TS 校验契约**（assemble_ts.py `run_all_validations`，~38 条）：存量 C7-C13 保留 + 新增 N1-N27。分级：硬阻断（结构不可能对，exit 1）/ 软阻断+豁免（默认拦，填 exemptions 放行，闸口①可见）/ warn。报错按五层分组。
   - **多步骤数据流模型**：每个 rule 有 step_type（full/aggregate/incremental_extract/merge）+ target_role（intermediate/target），多步骤间用 produces_for/reads 声明依赖。**中间表≠聚合**（target_role=intermediate 按"产出供谁消费"定义，可以是 aggregate/full/incremental_extract 任意 step_type）。complexity-playbook §四 是 step_type 决策权威，incremental-playbook 是增量设计权威。
   - **增量防臆想**（攻"只做主表"+攻"全量心智装增量"）：assemble_ts 硬校验 N14（标了增量但完全没增量处理；旧版"source 涉驱动表"析取恒为真已删）+ N28（增量资产至少两个规则——增量取数 + 终态增量更新，单规则直灌不被支持）+ N_INIT2（终态规则禁 truncate_table，**锚在 RS 增量声明上**——designer 忘标增量段按全量设计一样被拦）+ N15/N16。累积共建场景（多来源写同一中间表）标 `build_mode: accumulate`，配 dedup_strategy。
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
| **SQL 问题** | INSERT 报错含 COLUMN/TYPE/SYNTAX/DOES NOT EXIST；DQ 段 FAIL/MISSING（DQ SQL 报错或文件缺失） | coder 改语法（**恢复该规则旧会话**，不新开）|
| **数据质量问题** | UT 检查 FAIL：主键重复 / 空值 / 行数异常 | **退回 designer**（绝不给 coder）|
| **DQ 告警** | UT 报告 DQ 段 ALERT（非 0 行违规，带样例） | **闸口② 人判**（SQL 方向反→coder / 阈值口径→designer / 数据真脏→人定），不自动改 |
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

- **配置**：`~/.config/opencode/_references/rules/dws-design-dev/db-sources.json`（config 统一放 rules/dws-design-dev/，与其他项目隔离；install 不覆盖已有的；从 `skills/dws-coding/assets/db-sources.example.json` 拷）。所有 config 路径集中由 `design-dev-shared/scripts/config_paths.py` 解析（`config_dir()` + `db_sources_path()` 等）——改基址只动这一处。
- **账号分 role**：`admin`（DDL 建表删表）/ `etl`（SELECT/INSERT 数据读写）。每数据源必配这两个 role。
- **按 schema 选源**：`schema_mapping` 映射 schema→数据源名，找不到回退 default。
- **高层入口**：`create_executor_for_schema(schema, role="etl", config_path="")`——调用方只传 schema+role，不碰配置。低层用 `create_executor(config_path, source, role)`。
- **statement_timeout**：连接建立时按 `security.timeout` 设一次，复用连接都带超时，防 agent kill 进程留僵尸查询。
- **sample_blocks**：`security.sample_blocks`（开发环境配>0，UAT/生产配0）。**语义是"快速失败闸门"不是最终审视**：ut_execute 对 truncate_table 规则先采样试跑 INSERT（类型转换/约束类错误秒级暴露），通过后 TRUNCATE 清试跑数据再全量执行——**UT 终审按全量结果**（SELECT 跑通≠INSERT 全量跑通，目标列类型转换靠行数据触发，纯采样漏检）。`resolve_sample_blocks(config_path, cli_value)` 解析：CLI 传值（含 0=强制不采样）优先，否则读配置，否则 0。`inject_tablesample(sql, n)` 用 sqlglot AST 按 JOIN 类型注 TABLESAMPLE SYSTEM(n)：**FROM 主表 + INNER/逗号/CROSS JOIN 表注**（必要表，控制总量），**LEFT/RIGHT/FULL JOIN 从表不注**（外连接侧保留全量，避免切片后关联不上变 NULL），CTE/子查询里的表不注。

**三个 skill 脚本目录都靠相对路径推算 design-dev-shared**：
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
```

---

## 编码约定

- **运行时提示零废话**：commands / SKILL.md / agent.md 是给 agent 消费的运行时提示——每个字要么改变行为（指令/条件/枚举/路由/边界），要么删；"为什么"的解释、口语注解、重复强调一律不进，知识归 AGENTS.md / tool-registry（维护者文档）。写的时候自问：删掉这句 agent 会做错吗？不会就是废话。
- **类型风险判定唯一源 = type_compat.py**（三档：方向性安全放行 / 安全方向仅长度紧→常规档 / 其余问人），pipe 只按脚本分组提问不承载判定；判定口径变更只改 type_compat 一处。**安全处理的边界定调（2026-08-31）**：它守的是"转换动作"——防个别脏值炸批（失败模式从崩溃变为可检测降级：非法值置 NULL 被 DQ 抓），**不兜底值域**——正常数据装不下目标定义（数值整数位溢出/字符必截）= 模型设计问题（mapping 目标类型定窄），退 BA 改模型；置空/截断策略必须人显式拍板。**值域探测（precheck `_check_value_range`）**：pg_stats 统计信息版（零成本读 catalog）——数值统计上界整数位 > 目标 precision-scale → error 阻断退 BA；字符 avg_width 超目标长度 → warn 披露（闸口①人确认）；无库/无统计 → warn（UT 兜底：值域类报错 numeric overflow / value too long 分流退人禁回 coder）。
- **改工具同步注册表**：加/改/删任何脚本（skills/*/scripts 下的 .py），必须同步更新 `docs/tool-registry.md`（含"读 ts[rules/init]"列——init 下游物化的进度表）。agent 行为/工作流改动同步各自 SKILL.md（唯一源），agent.md 只管角色+权限+指针，不复述工作流（防双写漂移）。
- **★ 工具是服务，不是枷锁**：agent 的辅助工具（explore / schema_query / pick_fields 等）是"遇到不确定时拿来用"的服务——SKILL 引导一律写"不确定 X 时可调 Y 确认"，**不写成"做 X 前必须先 Y"的强制前置步骤**（枷锁式引导会让 agent 每次机械跑一遍工具，丢掉自己的判断）。区分两类：command 调的管线脚本（preprocess / assemble_ts / ut_* 等）是**流程节点**，按步骤必跑；agent 内的辅助工具是**按需服务**，agent 自己判断要不要用。
- **黑盒运行时的分层落盘（2026-08-31 定稿，内网团队实证）**：内网 codeagent（基于 1.2.27 魔改）bug——≥2 层子 agent 丢 write/edit 工具、丢 read 的额外目录权限、agent 定义部分配置不生效（同版本本机正常，已排除 modelID 判定/permission 下压/childToolDenies，结论=魔改行为；**平台修复后本规范整体退役**）。唯一标准写法（规定动作，三要素）：单引号 here-string + `[IO.File]::WriteAllText(path, $c, UTF8Encoding($false))` + 结束标记 `'@` 顶行首独占一行。**黑名单（实证坑）**：Out-File/Set-Content 的 utf8（BOM）、`echo >`（中文乱码）、双引号 here-string `@"`（`${}` 被插值吞）。读 skill 引用：read 工具优先，被拒即 fallback bash `Get-Content -Encoding UTF8 '<绝对路径>'`（环境自适应，不预设 bug 边界）。标准在 dws-coder.md/dws-designer.md；失败上报禁换变体试错。
- **禁止 glob 通配匹配文件**（CLAUDE.md 红线）：文件名由生成脚本命名规则确定，查找用确定的文件名拼接（如 `f"create_table_{table}.sql"`）。命名约定变了就改查找代码，不靠通配兜底。
- **测试不连库**：用 Python dict/fake executor 构造数据，`tests/conftest.py` 把三个 scripts 目录加进 sys.path。数据工厂：`make_rs_input`/`make_design_decisions`/`make_ts_json`（基础）+ `make_incremental_rs_input`/`make_incremental_decisions`/`make_accumulate_decisions`（增量/累积共建场景）。`make_design_decisions` 默认产出能通过全部新校验的合法 decisions，测试通过传参注入坏值。
- **Python snake_case**，提交规范 `feat/fix/refactor/docs: 描述`。
- **designer 只改设计不改 SQL**；coder 只接 SQL 语法类问题。职责边界在 agent permission 白名单里硬约束。
- **rs_input 双文件**：`rs_input.json`（field_mappings 行对象列表，assemble_ts/precheck 脚本读）+ `rs_input_view.json`（compact 分块紧凑视图，designer 读）。同一次 preprocess 产出（view 是 build_compact 从 input 派生），天然一致。designer 用 Read 读 view（23KB）而非 input 全文（120KB）。view 的段：增量横幅/tables/direct/processed/target/**explore（RS L01 数据探索——量级/空值率；缺失也标注"未提供"，让 designer 知道没有而不是不知道有没有）**/null_in_scene/join_type_risk/dq/schedule；processed 条目带**『决策』标记**（类型风险已人定回写的字段——勿推翻方向，译守卫式转换口径）。
- **口径引用骨架（引用门禁 LG，三段对账）**：事件本质——mapping 加工逻辑是人话，输入侧只尽力而为；designer 是唯一语义推理环节（**未限定字段的表归属是他的判断，脚本只做确定性的事不猜**）；交卷后产出必须 100% 可结构化解析（引用一律 `别名.字段`，限定形态提取是确定性动作），**引用门禁（LG）三查一道门**：N36 格式（hard，未限定标识符纯语法零漏报）/N38 存在（hard，限定引用查 schema_cache/tmp；无库降 warn）/ N37 完整（warn，与原文提取对差——尽力而为增益）。链路：preprocess 提取原文引用存顶层 `_logic_refs`（尽力而为，脚本专用不进 view）+ view refs 中性提示（限定引用原样+未限定词，多表同名是事实，归属不猜）→ 门禁 → assemble_ts 按引用集补全字段血缘（direct 串/processed.refs，**表归属从 source_tables 解析**）→ check_sql 对账 processed.logic 引用 ⊆ SQL 引用 → gate_summary `--rs` 差异表（机器验"没变的"人审"变的"）。coder 永不接触原文。N30 管 joins/filter/join_safety 的引用存在性（关联声明域）。
- **design_logic 形态 = SQL 表达式 +（全角括号口径说明）**（2026-08 定调，防翻译漂移——实证：del_flag 口径被转述后 coder 加空串条件语义反转）：原文是表达式→designer 审查后**原样保留**+理解句（方言不管，DWS 兼容 nvl/decode，不兼容 UT 暴露归 coder 机械转写）；原文是人话→designer 翻译成表达式+歧义决策记录（拿不准标"需业务确认"）；禁用裸"空"字（写 NULL 或空串）；宁可带假设标注的表达式，绝不退回纯人话。**说明一律放全角括号（）内、表达式只用半角**——N36 剥全角段后检查（说明里提到的字段名不误拦；结构规则封闭，SQL 表达式不可能含全角括号）。**落盘单行归一**（`normalize_logic_line`，装配侧单点，引号串保护）——designer YAML 块标量的换行不进 ts.json，消费者零加工。coder **表达式直搬禁改口径**（机械转写允许/疑义上报），check_sql 表达式口径对账兜底（case when 归一化包含匹配，不匹配**归提示级不阻断**——方言机械转写属合法，闸口②人核；check_sql 输出分级 error/提示两档，退出码只由真问题定）。
- **ts 多步骤数据流模型**：rule 有 step_type（full 单规则直灌/装配/非聚合中间加工 / aggregate 聚合产出 / incremental_extract 增量取数到 tmp / merge 合并 tmp 到目标）+ target_role（intermediate/target）。中间表和目标表可有同名字段（按 (表,字段) 查重，不按全局）。多步骤依赖用 produces_for/reads 声明（与 data_flow.dependencies 互补），assemble_ts 校验依赖闭合（N9-N12：produces_for 非空、reads 非空、双向对账 N10b、依赖顺序 N10c、循环检测 N10d）。简单全量走 full 老路不受影响。**中间表≠聚合**，step_type 决策权威是 complexity-playbook §四。
- **ts 两视图分界 + rules.fields 三桶**（2026-08-27 重构，229d718）：唯一分界=「这个键回答『表是什么』还是『规则怎么产』」。`tables` 纯表元数据——字段三键（名/类型/注释）+物理属性+build_mode，**DDL 唯一源**，加工语义全迁出。`rules.fields` 三桶（coder 唯一消费源）：**processed**（target+logic+refs，designer 显式口径强制进此桶，不受 rs_input 分类影响）/ **assign**（target+value，审计3条每规则自动补，业务赋值同构）/ **direct**（一行一串 `alias.col [AS target]`，串即完整血缘；**同名也写 AS**——产物按消费者零加工形态交付）。桶名即分类，无 transform_type 细分。ts 已无 field_logics/source_refs/tables 三语义键/`_global.audit_fields`（decisions 输入接口不变，装配展开成桶）；旧 ts 由 `ts_compat.normalize_ts` 内存升级（幂等），slice/check_sql/export/fence/opt 读旧结构全走此路。check_sql 字段覆盖=三桶并集。
- **累积共建模式**（多来源写同一中间表，常见于去重/union 场景）：中间表标 `tables.{表}.build_mode: accumulate`，同表字段可重叠（C9 在 accumulate 模式放行）。排重策略由 designer 定（rule 级 `dedup_strategy`：key/priority/reason），coder 翻译成 SQL。详见 incremental-playbook §三/§四。
- **TS 校验契约分级**（assemble_ts.py）：硬阻断（N1-N4 锚点 / N5 加工字段必写 logic / N6-N12 路径 / N14-N15 增量 / **N28 增量资产≥2规则（单规则直灌不被支持）** / N18-N21 工程 / **N30 joins 条件/filter/join_safety 引用存在性（vs schema_cache/tmp，专抓 rn=1 开窗残留；无 cache 降 warn——加工字段口径引用归 LG/N38）** / **N_JOIN2 自设关联键类型比对（cache 门控全量：裸等值对两侧类型查 schema_cache/tmp 类型，type_compat.join_key_pair_risky 判跨大类，cast 声明/内联 cast/N_JOIN1 检出对与豁免放行——补 N_JOIN1 只管 mapping 声明域的空档；无类型跳过不猜）** / **N31 别名一规则一表（rs_input 别名与 reads tmp 别名冲突即拦）** / N22 参数 / N25 design_approach / **N35 赋值翻译闸（赋值+非标准字面量+无 designer 翻译→拦；标准审计字段豁免、值按模板归一。错标识别后置到 designer 之后——输入层判不了自然语言，"处理过没有"是过程问题可判；preprocess 不改字段类型，如实反映输入）** / **N36 引用门禁·格式（design_logic 未限定英文标识符即拦——纯语法零漏报不依赖登记处；剥全角括号说明段/引号串/`${}`，噪音词/函数/SQL类型词/单字母豁免；中文提字段机器不可见=语义边界归闸口①）** / **N38 引用门禁·存在（design_logic 限定引用查 schema_cache/tmp——无 cache 降单条 warn）** / **N_DQ5 violation_condition 引用存在性（跨表级 DQ 合法引用资产内任何表——比对来源表/目标表数据量的子查询含 schema.table 是常态：schema.table 形态查资产表名集合（rs_input 就有，无 cache 也拦）；别名.字段查全域=目标表字段∪cache 源表字段（无 cache 降 warn 不硬拦——宁放过，源表字段查不到））** / **N_INIT2 增量目标禁 truncate（锚 RS 增量声明，不依赖规则自标）** / N_INIT1 init 规则禁手填 load_mode / N_INIT_MODE·N_INIT_GROUP 合法值）/ 软阻断（N16-N17 增量合并，填 exemptions 放行）/ warn（N23-N24/N27/**N29 design_logic 与 mapping 原文完全一致（=表达式保留但缺口径说明句，或人话未翻译；两边归一后比较）**/**N32 joins 引用别名无表绑定**/**N33 tmp 命名不合规范（目标表主体+_tmp+序号）**/**N34 孤儿 field_logics（写了口径但字段不在 targets，防静默丢）**/**N37 引用门禁·完整（mapping 原文引用集 `_logic_refs` vs design_logic 引用集对差——尽力而为增益，门禁不依赖它；designer 多出的不报，幻觉由 N38 拦）**/**N_DQ4 dq_rules 缺 violation_condition（存量兼容软引导）**/N_INIT3 delta机器残留/N_INIT4 init口径空）。分层：L0-L4/LC/LA/LD/**LI(初始化设计)**/**LG(引用门禁——加工字段引用 格式/存在/完整 三查一道门，designer 交卷后产出必须 100% 可结构化解析）**/**LD 含 N_DQ4/N_DQ5（DQ 版 design_logic：violation_condition 表达式 coder WHERE 直搬）**。完整契约见 assemble_ts.py 的 `run_all_validations` + `ValidationResult`。
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

- `skills/new-pipe/SKILL.md`——★ 新建编排剧本唯一源（改流程先读这个；`commands/new-pipe.md` 是薄壳入口）
- `agents/dws-engineer.md`——★ 编排 agent 岗位定义（身份/权限/契约参数/铁律）
- `docs/integration-contract.md`——★ 总控对接契约（调用方式/参数/部署前提）
- `skills/dws-design/SKILL.md`——★ **五层决策骨架**（designer 思考主线，改设计流程先读这个）
- `skills/dws-design/references/incremental-playbook.md`——增量设计全集（数据流/累积共建/排重/初始化/豁免）
- `skills/dws-design/references/complexity-playbook.md`——复杂度评估 + CTE/物化决策 + step_type 决策树
- `skills/dws-design/references/design-guide.md`——物理设计决策（分布键/分区）+ 依赖类型（精简版）
- `skills/dws-design/assets/ts-template.json`——ts.json 权威结构定义
- `skills/dws-design/assets/design-decisions-template.yaml`——designer 产出格式（含 build_mode/dedup_strategy/data_volume/exemptions）
- `docs/architecture/architecture.md`——架构（环境/四区/决策记录）
- `eval-suite/idle-task-prompt.md`——闲时任务（常规巡检：健康回归/文档-代码一致性/死代码扫描/覆盖缺口 + 当期专项插槽）

## 已知滞后项

`CLAUDE.md` 和 `README.md` 仍描述旧的 `dws-pipeline-*` 9-skill 结构，与实际不符。实际是 `dws-design` + `dws-coding` + `design-dev-shared` 三个 skill + 两个 agent（designer/coder）+ 一个 command（new-pipe）。改这两个文件时以本 AGENTS.md 和实际代码为准。

> CLAUDE.md 的"全局认知/架构共识/历史推理"部分仍有参考价值，但涉及**当前实际结构、设计流程、校验契约**的内容以本 AGENTS.md 为准（CLAUDE.md 不再同步细节改动）。

### 本轮改造（设计思维重构 + TS 校验契约补强，2026-08）

design-guide.md 已从 335 行大杂烩拆分为：design-guide（物理决策，70行）+ incremental-playbook（增量全集）+ complexity-playbook（复杂度/物化/step_type）。SKILL.md 的 9 步操作清单已重构为**五层决策骨架**。assemble_ts.py 新增 `run_all_validations`（~38 条校验，五层分组）+ `ValidationResult`（分层报错）+ 软阻断豁免机制。design_decisions 模板补 `build_mode`/`dedup_strategy`/`data_volume`/`exemptions`。preprocess.py 内嵌的死代码 precheck 副本已删除。测试 419→465。

### init 双管道模型改造（2026-08，设计侧 + 下游物化 已全通）

修掉增量场景的致命 bug：增量目标 load_mode=truncate_table 导致每次增量全删全插。根因是一个 rule 一个 load_mode 装不下 init/增量两种写入。改为**双管道模型**：增量管道（`rules`，load_mode=merge 等）+ init 管道（`init` 段，load_mode 恒 truncate_table）。

- **设计侧**：新增 LI 层校验（N_INIT1/2/3/4 + mode/group_mode 合法值）+ `build_init_section` 装配器（7 不变量补全 + core_from 抄口径，幂等）。两种 mode：derive（无 delta 机器，克隆增量物化 init.rules）/ explicit（有 delta 机器，designer 写 core_from+joins，装配器补不变量）。group_mode：inline（同组 P_FLAG 选跑）/ separate（独立规则组+独立任务）。ts.md §8 不再按 load_mode 藏增量规则 + 新增初始化设计段。
- **下游物化**：slice_ts 查 ts.init.rules + derive 切片带 clone_source（源 SQL+filter/init_filter，coder 适配写 INIT.sql，**不**用脚本派生——code 归 coder）；assemble_export 合并 init 规则发执行行（inline P_FLAG 运行条件 / separate init 任务 + 计数）；assemble_ts tasks["init"]（separate）+ P_FLAG 注入（inline）；ut_precheck/ut_execute **init 阶段先建基线→增量阶段后 merge**（符合现实部署顺序，prev_failed 跨阶段级联）。
- incremental-playbook §八 重写（双管道/derive-explicit/坍缩逻辑/装配器）。测试 +21（设计侧）+10（下游）。669 过 2 skip。
- 非破坏：无 init 的资产全程不受影响（slice/export/ut 都 `if init_rules`）。

### DQ RS 驱动改造（2026-08）

DQ 产出从"designer 随机决定"改为"**完全跟随 RS**"，消除"一次有一次没有"的不稳定。核心：
- **DQ 100% 跟随 RS**：`rs_input.dq_requirements` 非空 → designer 翻译产 `dq_rules`；为空 → `dq_rules` 留空。
- **designer 是翻译者**（不是搬运工，类比 field_logics 写 design_logic）：scope/check_type/rule_name 跟 RS 一致，**violation_condition 写违规条件的 SQL 表达式**（检查对象=目标 F 表，如 `t.order_amount IS NULL`——DQ 版 design_logic，coder WHERE 直搬不再翻译自然语言），rule_desc 写口径说明（阈值来历/告警级/方向备注）。
- **取消"标准三项"系统兜底**（主键唯一/审计非空/记录数不再无条件产）。
- assemble_ts 的 LD 层校验：N_DQ1（硬阻断，RS 有 DQ 但 dq_rules 空）/ N_DQ2（warn，条数偏少）/ N_DQ3（warn，RS 无但自加）/ **N_DQ4（warn，缺 violation_condition——存量兼容软引导）/ N_DQ5（硬，violation_condition 引用目标表没有的字段）**。
- DQ 调度任务条件化（dq_rules 空不建 tasks["dq"]）；coder 条件化调用（dq_rules 空不调）。
- preprocess build_compact 加 `dq` 段（designer 读 view 就看到 RS 的 DQ 需求）。
- assemble_dq.py 已退役删除（2026-08）：eval-suite 改走 coder 生成 DQ（对齐生产 4c），两路 DQ 产出统一，无脚本兜底。
- **DQ 工具契约（2026-08-28）**：slice_ts --dq 附**资产级 source_tables 并集**（跨表检查用 schema 全名）；check_sql 加 **--dq 模式**（括号/无 SELECT */行注释/表引用 ⊆ 检查对象+资产源表/schema 前缀/输出列含 business_key）——dws-dq SKILL 原"不跑 check_sql"已改；**输出列契约定死：业务键 + 违规字段本身（输出值不是字段名清单，列名=字段名）**；DQ 模板进 dws-dq 自己的 SKILL（DQ 知识跟 skill 走，不进 etl-templates）。
- **语义契约 + UT 执行验证（2026-08）**：DQ SELECT = **违规行探测器**——0 行=通过，非 0 行=告警；阈值/比例逻辑全收 WHERE/HAVING，工具只判行数。designer 的 rule_desc **必须写明违规方向**（防译反，例："违规=order_amount IS NULL"）；coder 输出业务键+违规值列、文件名 `dq_{check_type}.sql`（UT 按确定名找）。ut_execute 尾部内嵌 DQ 阶段（`run_dq_checks`：dq_rules 非空且数据完整才执行；COUNT 包裹判行数，告警才 LIMIT 采样）——三分结果：FAIL/MISSING 回 coder（SQL 类）；**ALERT（非 0 行）阻断出口（exit 1）**，闸口② 人判（SQL 方向反→coder / 阈值口径不合理→designer / 数据真脏→人定）；中间阈值结果依赖数据分布，人工确认预期。UT 零结果证明"SQL 可执行+当前数据不告警"，不证明阈值绝对合理。

### 工程治理：工具注册表 + agent 瘦身 + legacy 清理（2026-08）

- **工具注册表**（`docs/tool-registry.md`）：全管线脚本按**调用方**分组（command / designer / coder / imported），澄清"脚本住哪个 skill 目录 ≠ 谁调它"（preprocess/precheck 等住在 dws-design 但由 command 调）。含"读 ts[rules/init]"列——init 下游物化的进度表。编码约定加一条：**改/加脚本必须同步 tool-registry.md**（防漂移，之前 AGENTS.md 结构树已漏 pick_fields）。
- **agent 瘦身**：dws-designer.md（197→85 行）/ dws-coder.md（112→65 行）——把抄 SKILL.md 的工作流/工具用法削回指针（coder.md 自认"与 SKILL §2.4 保持一致 改动要同步"的双写消除），只留身份+权限+角色独有行为+工具清单。分层定型：tool-registry（工具WHAT）+ agent.md（岗位）+ SKILL.md（工作流唯一源）。agent.md 独有的关联决策（倒推 JOIN / INNER-LEFT）迁进 SKILL §2 第2层。
- **legacy 清理**：删 sql_validator.py / validate_ddl.py / verify_files.py（全仓查引用，零生产引用、零/孤儿测试）。assemble_dq.py / run_ut legacy main() 的整改原挂闲时任务六，**已完成（2026-08）**：assemble_dq.py 删除（eval-suite 改走 coder 生成 DQ，对齐生产 4c）；run_ut.py 删 legacy main() 成纯函数库（6a/6b 两阶段是唯一执行入口）。

### config 集中 + 产出目录分层 + 编排者铁律（2026-08）

- **config 集中隔离**：新建 `design-dev-shared/scripts/config_paths.py`（`config_dir()` + 各 config 路径，改基址只动一处）。4 个 config（db-sources / platform_config / schedule_config / schema_apps）统一放 `~/.config/opencode/_references/rules/dws-design-dev/`（与其他项目隔离）。7 个脚本的默认路径全部改用 config_paths。install.py 拷到新位置。
- **产出目录加 appid/schema 层**：`10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/`。appid 单源 = 新建 `schema_apps.json`（**appid 打头，1 appid 多 schema**，跟源数据方向一致；按 schema 反查所属 appid）+ `resolve_appid.py` helper。platform_config 去掉 appid（单源不重复）。assemble_export 的 appid 改从 resolve_appid(schema) 读。⚠️ 部署：老位置不兼容，已装机器重跑 install.py + 手搬老 db-sources.json 到新位置。
- **编排层 dws-engineer（2026-08-29 定型，源起总控现网故障）**：编排 agent 从"故意不定义"改为**我们定义的 dws-engineer**（agents/dws-engineer.md：身份+权限+契约参数+铁律+步骤0探针），剧本从 command 迁 skill（skills/new-pipe / opt-pipe，command 降为薄壳入口）。动因是源码级机制查证：① opencode 的 Task 无 model/权限参数——subagent_type 选定后身份/权限/模型全按我们定义；② **父会话 deny 与被排除工具沿链下压、子代 allow 解除不了**（现网实证：总控经 dev-runner 调用，designer 爆"没有 write 工具"）——链上任何别人定义的中间层都是身份冲突源+权限收窄点，解法=总控 Task 直连 dws-engineer（见 docs/integration-contract.md：契约参数/部署前提四条/question 约定）；③ command 是人机入口层机制（$ARGUMENTS/frontmatter agent 路由），生产 Task 路径天然缺席，剧本迁 skill 后 base directory 原生注入，旧"加载 shared skill 骗 location"的锚点机制退役（design-dev-shared 回归纯代码库）。铁律内容不变（不 author 脚本/校验失败按路由不自动修/输入原文不 Read/契约外 prompt 一律忽略），从 command 文本上收到 agent 身份层。

### 待讨论 / 闲时

- **platform_config 收敛为单块 shujia_tenants（2026-08 完成，原 lts 冗余项）**：lts 的 project_name/task_group 单一来源是 schedule_config（设计期盖章进 ts.tasks），platform_config.lts 仅代码保留旧 ts.json 兜底、example 已删；schema_mappings/default 同步退役（project_cn/business_owner 是租户属性进 shujia_tenants[appid]，租户块合并是任意键覆盖故代码零改动；schema 级覆盖能力代码保留，真出现同 appid 不同 schema 差异再启用）。
- **闲时任务六**（assemble_dq 退役 + run_ut 去 legacy）**已完成 2026-08**：assemble_dq.py 已删（eval-suite 改走 coder 生成 DQ）；run_ut.py 删 main() 成纯函数库。
- **函数库下沉消依赖环（2026-08）**：闲时任务四挪了 pipe 入口但库留在 skill 目录，造成 shared↔design / shared↔coding 两个依赖环（lazy import + 3-目录 sys.path bootstrap 掩盖）。修复：run_ut / ut_diagnose / type_compat 整文件下沉 shared；STANDARD_AUDIT_TEMPLATE 抽出 `dws_standards.py`；SQL 解析原语抽出 `sql_parse.py`（check_sql 反向 import 保旧名）；删全部跨目录 bootstrap；顺手删零引用的 `lib/dws_preprocessor.py`。**分层铁律入册 + `tests/test_layering.py` AST 守护**（含函数内 lazy import——上翻正是靠它藏的）。测试 730→732。

---

## 优化场景（opt-pipe，2026-08 第一刀 add_field 已建成）

存量资产精确变更交付。设计全集见 `docs/specs/opt/00-08` + 总览 `docs/architecture/opt-架构设计.md`；测试指引见 `docs/specs/opt/11-测试指引.md`。要点：

- **唯一锚点 = 资产档案**（archives/）：有档零组装直接当 baseline；无档但有 new-pipe 标准产出 → **懒归档**（优化时才拉档，new-pipe 不做归档步骤——YAGNI）；都没有 → 收 baseline_v1.json（逆向侧 peer agent 文件交接，**不调它的脚本**）入料建档；优化交付写回档案（循环链）。**不验真输入**（默认准确，压力给供方）。
- **输入（真实格式 2026-08-21）**：需求包 = 全量 mapping（备注列 `{YYYYMM}版本{动词}` 标记变更，动词可扩展归类）+ RS（3.3 变更记录表定位版本 + 正文版本锚定段给口径）；版本锚点 = 最新"优化"行日期归一 YYYYMM（日期↔YYYYMM 搭桥，v2.0 序号不用）。编排者不读输入原文——分拣解析全在 preprocess_opt（--input-dir）。
- **两级声明 + 三段审计**：change_request（业务说了什么，preprocess_opt 产）+ ts.change 段（落位，designer 声明、assemble_ts_opt 组装）→ fence_check（ts 级围栏，恰好等于双向）→ sql_fence_check（SQL 级围栏，**闸门单点在 pipe**）。回路铁律：产物变→围栏重跑→才进 UT。
- **存量语义不补**（主键/粒度/关联安全留空+豁免，双跑兜底）；新 JOIN 必须 join_safety（opt-playbook）。
- **UT = ut_opt.py**（独立入口零触碰 ut_precheck/ut_execute）：ALTER 应用（表不存在=环境归人）+ 双向 MINUS 输出对比（冻结列零差异）+ INSERT 全量；主键豁免、空值只查新列。
- **制品 = 严格 patch**：assemble_ddl_opt（ALTER 变更单+全量 DDL+差异审计）+ artifact_patcher（xlsx/yml 交付副本+patch 说明，存量声明漂移不碰）；ts 不是制品再生源（原则8）。
- **对存量零接触**：全部新脚本（shared 7 个 + dws-design 1 个 + slice_ts 加法扩展 --baseline-sql）；assemble_ts/ut_*/assemble_ddl 本体未动。
