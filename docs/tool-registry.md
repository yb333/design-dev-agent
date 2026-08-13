# 工具注册表（Tool Registry）

> 全管线脚本的**唯一目录**。每个工具一行，高信号列。
> 已清理死代码（sql_validator / validate_ddl / verify_files 已删，零生产引用零测试）。
> **维护约定**：加/改/删脚本时**同步这张表**（写进 AGENTS.md 编码约定）。漂移从这里一眼看出。
>
> **关键区分**：脚本**住在哪个 skill 目录**（按"阶段"组织：设计阶段脚本放 dws-design、编码阶段放 dws-coding）
> ≠ **谁实际调用它**。本表按**调用方**分组——这才是"谁会用它"的真相。
>
> 末列「读 ts[rules/init]」是 init 下游物化进度表。Chunk 2 已接通：slice_ts / pick_fields / assemble_export / ut_precheck / ut_execute 都读 ts.rules + ts.init.rules（标 **both**）。check_sql / run_ut.main 尚未接通（init 走 slice_ts 间接覆盖；run_ut.main 是 legacy 不走）。

---

## ① command 调用（new-pipe.md 编排，主线管线脚本）

> 这些脚本虽住在 dws-design / dws-coding 下（按阶段归类），但**调用方是编排 command**，不是 agent。

### 预处理 / 输入校验（设计阶段前端，住 dws-design）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `preprocess.py` | mapping.xlsx + RS.md → rs_input.json（完整，给脚本）+ rs_input_view.json（compact，给 designer） | 步骤 1 | mapping+RS → `rs_input.json` / `rs_input_view.json` | 不读 ts（还没产） |
| `precheck.py` | 输入完整性 + **连库类型检查**（pg_catalog 批量查，24h schema 缓存）+ 类型风险决策骨架 | 步骤 1 | rs_input.json → precheck_report.md / `_internal/schema_cache.json` / `_internal/type_risk_decision.yaml` | 不读 ts |
| `fill_type_risk_decision.py` | 把人的类型风险决策填进 precheck 的骨架（免手写嵌套 YAML） | 步骤 1 | 决策参数 → 改 type_risk_decision.yaml | 不读 ts |
| `gate_summary.py` | 闸口①设计摘要（表/规则数/场景/字段统计，确定性） | 闸口① | ts.json → 摘要 | ts.rules / ts.tables / ts.meta |

### 执行计划（编码前，住 design-dev-shared）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `dispatch_plan.py` | 读 ts.json 输出编码段执行计划（ddl/dq/etl_rules/init_rules/groups），pipe 一次拿全并行发起，不手工解析判断 | 步骤 4-0 | ts.json → 执行计划 JSON（stdout） | **ts.rules + ts.init.rules** + ts.dq_rules + ts.data_flow |

### 制品生成（编码阶段后端，住 dws-coding）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `assemble_ddl.py` | ts → DDL（CREATE TABLE/VIEW + COMMENT + 分布键 + TO GROUP） | 步骤 4 | ts.json → `ddl/*.sql` | ts.rules + ts.tables（init 复用 tmp 无新 DDL；Chunk 2 确认不重复建） |
| `assemble_export.py` | ts + ETL + DDL → execution_tasks.xlsx（10 sheet）+ schedule_tasks.xlsx + manifest | 步骤 7.5 | ts.json + etl/ + ddl/ → `export/*.xlsx` | **ts.rules + ts.init.rules**（init 执行行：inline→P_FLAG 运行条件 / separate→独立 init 任务；计数含 init） |
| `assemble_dq.py` | DQ SQL（标准三项）| **已弃用**（DQ 改 RS 驱动后仅 eval-suite 历史复现用） | ts.json → dq/*.sql | ts.dq_rules |

### UT（需数据库，住 dws-coding）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `check_db.py` | DB 探活（db-sources.json + 连通性，决定要不要跑 UT） | 步骤 6（门） | ts.json → DB_OK / NO_DB_SOURCE | ts.meta（不涉 rules） |
| `ut_precheck.py` | 快速 UT 预检（回退 + DDL + SELECT 跑通，秒级，不写数据） | 步骤 6a | ts.json + etl/ + ddl/ → PASS/FAIL | **ts.rules + ts.init.rules**（init-阶段先→增量-阶段后，有序两阶段） |
| `ut_execute.py` | UT 执行（load_mode 预处理 → INSERT → UT 检查 → 报告，分钟级） | 步骤 6b | ts.json + etl/ + ddl/ → ut_report.md / `_internal/ut_sql/{rule}.sql` | **ts.rules + ts.init.rules**（init 先建基线→增量在基线上 merge；prev_failed 跨阶段级联） |
| `run_ut.py` | **UT 函数库**（wrap_insert / wrap_write / run_ut_check / inject_tablesample / substitute_params 等，被 ut_precheck/ut_execute import）+ legacy `main()` 单执行器（new-pipe 不直接调，走 6a/6b） | 函数库：ut_precheck/ut_execute 用 | ts.json + etl/ + ddl/ → 报告 | **仅 ts.rules** + schedule_groups |

### legacy 校验
> 已删除（2026-08 清理）：`sql_validator.py` / `validate_ddl.py` / `verify_files.py` —— 零生产引用、零测试（validate_ddl 的孤儿测试一并清掉）。`CLAUDE.md` / `eval-suite/idle-task-prompt.md` 里还有提及，那两份是已知滞后文档，不再同步。

---

## ② designer agent 调用（设计子 agent 内部，住 dws-design）

| 工具 | 干啥 | 何时调 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------|------------|-------------------|
| `assemble_ts.py` | rs_input + design_decisions → ts.json + ts.md；跑 ~40 条校验（五层+LI） | designer 写完 decisions 后组装 | rs_input.json + design_decisions.yaml → ts.json / ts.md | 读 decisions.rules **+ decisions.init**（Chunk 1 已接通 init 段） |
| `explore.py` | JOIN 键唯一性探查（count vs count distinct，只读单表，不 JOIN） | designer 第4层关联安全 | ts.json + 表/键 → 结论 | ts.rules / ts.tables |
| `schema_query.py`（住 design-dev-shared，**designer/coder 公共**） | 查 schema_cache 字段存在性（--column 单查/列全表；只读缓存不连库，与 explore 连库互补） | designer 写 design_logic 引用 mapping 外字段前（设计时验证一次，coder 信任 design_logic；coder 不确定时兜底直调） | ts.json + schema.table → 存在性/字段清单 | 不读 ts（读 `_internal/schema_cache.json`） |

---

## ③ coder agent 调用（编码子 agent 内部，住 dws-coding）

| 工具 | 干啥 | 何时调 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------|------------|-------------------|
| `slice_ts.py` | 切单规则上下文为 YAML（避免大表上下文爆炸） | coder 每规则起手 | ts.json + rule_code → YAML 切片 | **ts.rules + ts.init.rules**（查两处；derive init 切片带 clone_source：源 .sql + filter/init_filter） |
| `pick_fields.py` | 直取字段查询（list/alias/field/table-fields）；import slice_rule；`--table-fields` 的查缓存能力来自 shared/schema_query 库 | coder 写直取字段时 | ts.json + rule_code → 字段行；读 schema_cache.json | **ts.rules + ts.init.rules**（随 slice_ts 接通 init） |
| `check_sql.py` | coder 的 SELECT vs ts 切片静态对比（字段覆盖/FROM 表/括号引号/无 SELECT *） | coder 写完自检 | SELECT.sql + ts.json + rule_code → PASS/FAIL | **仅 ts.rules**（Chunk 2） |

---

## ④ imported（非直接调用，被上述脚本 import）

| 模块 | 干啥 | 被谁 import | 所在 |
|------|------|------------|------|
| `dws_db.py` | DB 连接抽象（DBExecutor + PsycopgExecutor）+ diagnose_connection + sample_blocks | precheck / ut_precheck / ut_execute / check_db | design-dev-shared/scripts |
| `type_compat.py` | 类型兼容判断（assess_type_risk + RISK_LABEL_CN） | precheck | dws-design/scripts |
| `lib/dws_preprocessor.py` | 预处理辅助 | coding scripts | dws-coding/scripts/lib |

---

## init 下游物化进度（Chunk 2 已落地 2026-08）

| consumer | 调用方 | 状态 |
|----------|-------|------|
| `slice_ts.slice_rule` | coder | ✅ 查 ts.rules + ts.init.rules；derive 切片带 clone_source（源 .sql + filter/init_filter） |
| `pick_fields` | coder | ✅ 随 slice_ts 接通（import slice_rule） |
| `assemble_export` | command | ✅ 合并 init 规则发执行行；inline→P_FLAG 运行条件 / separate→init 任务；计数含 init |
| `ut_precheck` / `ut_execute` | command | ✅ init-阶段先（建基线）→增量-阶段后（在基线上 merge）；prev_failed 跨阶段级联 |
| `assemble_ts` tasks | designer | ✅ separate 模式实例化 tasks["init"]；inline 注 P_FLAG；derive 物化 init.rules |
| `new-pipe.md` 步骤 5b/6 | command | ✅ init coder 条件循环（5 后）；UT init-先说明 |
| `assemble_ddl` | command | ✅ init 复用 tmp（build_tables 按表名去重，无新 DDL） |
| `check_sql` | coder | ⚠️ 未直接改，但 init 切片经 slice_ts 解析，coder 自检流程不变 |
| `run_ut.main` | — | ⚠️ legacy 单执行器未改（new-pipe 走 6a/6b 不用它） |

derive 模式 init SQL：**不**用脚本字面派生——改由 coder 适配（slice_ts 带 clone_source，coder 读源 .sql 改 filter）。code 归 coder。
