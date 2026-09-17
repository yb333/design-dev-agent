# 工具注册表（Tool Registry）

> 全管线脚本的**唯一目录**。每个工具一行，高信号列。
> 已清理死代码（sql_validator / validate_ddl / verify_files 已删，零生产引用零测试）。
> **维护约定**：加/改/删脚本时**同步这张表**（写进 AGENTS.md 编码约定）。漂移从这里一眼看出。
>
> **关键区分**：脚本**住在哪个 skill 目录**（按**调用方**组织：pipe 调的在 design-dev-shared、designer 调的在 dws-design、coder 调的在 dws-coding）
> = **谁实际调用它**。本表按**调用方**分组。2026-08 归位：pipe 管线脚本（preprocess/precheck/gate_summary/assemble_ddl/assemble_export/ut_precheck/ut_execute/check_db）从 design/coding 挪到 design-dev-shared，消除"agent skill 目录里混着 pipe 脚本"；随后**函数库下沉**（run_ut/ut_diagnose/type_compat 整文件 + STANDARD_AUDIT_TEMPLATE→dws_standards + SQL 解析原语→sql_parse），消掉 shared↔skill 依赖环。**分层铁律：shared 绝不 import dws-design/dws-coding（箭头单向：skill → shared）。**
>
> 末列「读 ts[rules/init]」是 init 下游物化进度表。Chunk 2 已接通：slice_ts / pick_fields / assemble_export / ut_precheck / ut_execute 都读 ts.rules + ts.init.rules（标 **both**）。check_sql 尚未直接接通 init（init 走 slice_ts 间接覆盖）；run_ut 是纯函数库（无 main），由 ut_execute 读 ts。

---

## ① engineer 编排调用（dws-engineer 按 new-pipe/opt-pipe 剧本调；2026-09 按消费者归位：单一消费者住自己 pipe/scripts，共用入口住 shared）

| 工具 | 干啥 | 何时调 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------|------------|-------------------|
| `check_env.py`（住 skills/new-pipe/scripts） | dws-engineer 步骤 0 环境探针：安装指纹对账（_install_meta.json）/ 关键文件存在性 / python≥3.10 / **运行时依赖逐包对账（requirements.txt vs 当前解释器——install 只对找到的解释器便利安装，权威闸门在此）**——环境故障第一秒暴露 | 剧本步骤 0（必跑） | --skill-root 可选（默认按安装布局推算） → exit 0/1 | 不读 ts |

> 调用方是**剧本（new-pipe/opt-pipe SKILL）**，不是 agent。住址：new-pipe 专属管线脚本住 `skills/new-pipe/scripts`（下述各节标注）；共用入口（preprocess/check_db/assemble_ddl/resolve_appid）+ 公共库住 `design-dev-shared/scripts`。

### 预处理 / 输入校验（preprocess 住 shared 共用；precheck/gate_summary/fill_* 住 new-pipe）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `preprocess.py` | mapping.xlsx + RS.md → rs_input.json（完整，给脚本；含加工字段引用提取存顶层 `_logic_refs`（尽力而为，引用门禁 N37 原料））+ rs_input_view.json（compact，给 designer；processed 段含 refs 引用提示） | 步骤 1 | mapping+RS → `rs_input.json` / `rs_input_view.json` | 不读 ts（还没产） |
| `precheck.py` | 输入完整性 + **连库类型检查**（pg_catalog 批量查，24h schema 缓存）+ 类型风险决策骨架 + **关联键类型对账**（join_condition × schema_cache，跨大类→JOIN_TYPE_RISK_PENDING 三选决策：转换/改关联键/接受，双侧采样证据，宁放过不误报） | 步骤 1 | rs_input.json → precheck_report.md / `_internal/schema_cache.json` / `_internal/type_risk_decision.yaml` / `_internal/join_type_decision.yaml`（决策回写 rs_input._join_type_risks/_join_type_decisions） | 不读 ts |
| `fill_type_risk_decision.py` | 把人的类型风险决策填进 precheck 的骨架（免手写嵌套 YAML） | 步骤 1 | 决策参数 → 改 type_risk_decision.yaml | 不读 ts |
| `fill_join_risk_decision.py` | 把人的关联键类型决策填进 precheck 的骨架（--pair-decisions '条件=>处置'，免手写 YAML；与类型风险同轮全爆一次问完） | 步骤 1 | 决策参数 → 改 join_type_decision.yaml | 不读 ts |
| `gate_summary.py` | 闸口①设计摘要（表/规则数/场景/字段统计 + 翻译引用对账差异表 `--rs`，确定性） | 闸口① | ts.json（+ 可选 rs_input.json）→ 摘要 | ts.rules（field_logics）/ rs_input `_raw_refs` |

### 执行计划（编码前，dispatch_plan 住 new-pipe）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `dispatch_plan.py` | 读 ts.json 输出编码段执行计划（ddl/etl_rules/init_rules/groups；**dq 字段已删**[2026-09-14 DQ 拆分]——DQ 前置步骤 2.5 由 producer 完成，不在编码段），pipe 一次拿全并行发起，不手工解析判断 | 步骤 4-0 | ts.json → 执行计划 JSON（stdout） | **ts.rules + ts.init.rules** + ts.data_flow |

### DQ 装配（2026-09-14 DQ 拆分：producer 产物 → dq.json，住 new-pipe；起调时点=assemble_ts 通过即跑，塞闸口①等待窗口）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `assemble_dq.py` | **DQ 校验渲染器**（2026-09-15 两跳并一跳精简：producer **直接产 dq.json+SQL**，无 decisions 中间产物/无独立评审材料）：校验 producer 的 dq.json+dq/*.sql（N_DQ1-3 RS 对照/N_DQ4 violation_condition 必填+mode 值合法/N_DQ5 引用对账[三段式/**禁 tmp**/引用存在，无 cache 源表侧降 warn]/N_DQ9 SQL 文件在位/N_DQ10 SQL 对账[**幻觉列**+FROM 域拦 tmp]）+ 补全（idx/sql_file 派生/mode 缺省 assertion/meta+dq 调度任务[lts_task_paths 解析]）+ ts.md §7 DQ 表格**追加式渲染**（主线章节字节不动，**评审就看这张表**——歧义随表格行内标注）。锚定声明/compare_sources 暂缓（opt DQ 变更低频精简优先，dq_impact 粗提兜底） | 步骤 2.5（producer 交卷后） | dq.json + dq/ + ts.json + rs_input.json → 补全写回 dq.json / ts.md | ts.tables（F 表字段）+ ts.rules（intermediate tmp 集）+ ts.tasks（dq 任务挂 view 下游）+ ts.design.business_key |
| `pick_dq_context.py`（住 skills/dws-dq/scripts——**producer 自有入口**，对齐 check_field[住 dws-design]/slice_ts[住 dws-coding] 模式，2026-09-15 归位自 new-pipe） | **producer 输入切片三件套**（不读 view 全量——DQ 会话独立小输入）：确定性闭包（RS 需求文本→目标字段种子→沿 transform_detail 引用展开传递依赖）+ 存疑显式标记（人话逻辑机器圈不动→标注交付不静默缺失）+ 按需查询服务（--query 关键词 / --field 字段名检索 mapping 原文段，深挖用）；**禁止读 mapping 全量**（漏圈静默+上下文稀释） | dws-dq-producer 起手（SKILL §1；剧本不直接调） | rs_input.json + ts.json → dq_context.json（或 --query/--field → 命中行） | ts.design.business_key + ts.tables（目标字段清单，target_field 键） |

### 制品生成（assemble_ddl 住 shared 共用；assemble_export 住 new-pipe）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `assemble_ddl.py` | ts → DDL（CREATE TABLE + I 视图（F 表配套镜像）+ COMMENT（视图用 COMMENT ON VIEW）+ 分布键 + TO GROUP） | 步骤 4 | ts.json → `ddl/*.sql` | ts.rules + ts.tables |
| `assemble_export.py` | ts + ETL → shujia_{表}.xlsx（10 sheet）+ lts_{表}.xlsx（3 sheet），无 manifest（取码脚本只读 Excel） | 步骤 7.5 | ts.json + etl/ → `export/*.xlsx`（视图走 ddl/ 通道部署，不发术加规则行） | **ts.rules + ts.init.rules**（init 执行行：inline→P_FLAG 运行条件 / separate→独立 init 任务；编码占位符出厂 GR_*/规则码/PV000N 三处闭合校验；租户ID=appid、组织简称/数据源/项目中文名/责任人全走 shujia_tenants[appid]（shujia_config[2026-09-10 自 platform_config 更名]收敛为单块），项目编码/英文名及子项目全套由内网取码脚本补；lts 调度路径以 ts.tasks 为准（lts_config 任务路径段设计期盖章；consts/dep_task_ids 同文件导出期段）；RULE 行带执行序列，TargetFields 来源字段 s.字段 形态，参数变量行每规则组一条；**LTS 段 2026-09 重写**：任务组合模型（f=[虚拟依赖]+[GETDATE 增量]+主job+tskdep×N / view=database 占位job+tskdep / dq·init=主job+tskdep）、taskParams 基础全集带值模板（方案 A）、tskdep 同 4 段/跨 5 段路径+JSON 全套（行归属恒=当前任务）、主 job 异步 POST 8 键、五条出厂校验（V_ 引用闭合/父节点闭合/P_ 供给链等）；**末尾输出制品完整度报告**（固定格式待补清单——闸口②后固定二选一的问题来源；选项2真值经 --sub-project-cn/--group-code/--init-group-code 注入）） |

### UT（需数据库；check_db 住 shared 共用，ut_precheck/ut_execute/ut_diagnose 住 new-pipe，run_ut 是 shared 公共库）
| 工具 | 干啥 | new-pipe 阶段 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------------|------------|-------------------|
| `diagnose_fanout.py` | **关联质量定位器**（--all 闸口① / --rule 6b 同构）：**逐表键唯一性=主判据**（通过=一句话不裸查不对照——键裸查重复是常态；不唯一=贴条件原文+输入声明对照[宁缺勿错：一致=输入侧退BA/不等=文本差异人核]+**join_safety 断言对照**[声明unique实测不唯一=证伪最高优先/声明false+reason=已知接受不重复弹/未声明=补声明]+重复组差异列+命中严重性）+ **整体试算**（按声明条件拼全链数行数：膨胀/丢行/空关联率+未命中样例；全通过却膨胀=矛盾信号贴全部条件原文）+ 驱动表 business_key 自检；字面量值形态开局修正（schema_cache）；NULL 键不算发散；单表故障隔离（降级不带条件查）；中间表闸口①跳过；COUNT(1) 口径 | 闸口①前 --all（披露不阻断）+ 步骤 6b ⓪ --rule | ts.json → stdout + `_internal/diagnose/fanout_{all\|rule}.md`（分规则全量，中间结论不吞） | **ts.rules（+init.rules）** joins/source_tables + design.business_key + `_internal/schema_cache.json`（值形态） |
| `check_db.py` | DB 探活（db-sources.json + 连通性，决定要不要跑 UT） | 步骤 6（门） | ts.json → DB_OK / NO_DB_SOURCE | ts.meta（不涉 rules） |
| `ut_precheck.py` | 快速 UT 预检（DDL 统一部署：回退成功/失败分色标识→建表→I 视图；**EXPLAIN ANALYZE 全量真实执行一次[2026-09-03 替代采样 SELECT]——真跑通+计划两门槛+顶层实际行数[多格式解析宁缺勿错]；字段级 NULL 归 6b** + **执行计划两门槛**[2026-09-02]：纯 EXPLAIN——不下推=官方判据 Data Node Scan（_REMOTE_TABLE_QUERY_ 佐证；首版误用 Row Adapter 已纠正）+ STREAM 算子数≤50（任意 type 含 PART 变体）——用未采样 SQL，计划原文全量落盘 `_internal/diagnose/plan_{rule}.txt` 可回溯，提示级不阻断性能人判 + **describe 列序对账**[2026-09-11]：`SELECT * FROM (…) LIMIT 0` 实际输出列 vs ts 结构源字段序（compare_column_order 纯函数四态：一致/缺列/多列/乱序），多/缺/乱序 FAIL 归 coder——按位置对齐的 INSERT 乱序=静默错位数据；describe 无列返回跳过披露；权威解释器是数据库，列清单改结构源[见 run_ut]后 coder 输出漂移的唯一守卫 + **DQ 兜底**[2026-09-14]：rs_input.dq_requirements 非空但 dq.json 缺失且 ts 无旧 dq_rules → fail loud exit 2，N_DQ1 的 UT 侧防线防 DQ 静默漏交付） | 步骤 6a | ts.json + etl/ + ddl/ → PASS/FAIL | **ts.rules + ts.init.rules + ts.tables[].fields**（init-阶段先→增量-阶段后，有序两阶段） |
| `ut_execute.py` | UT 执行（load_mode 预处理 → **全量 INSERT**[采样试跑已退役 2026-09-03] → UT 检查 → **DQ 检查（数据完整时，0 行=通过/非 0 行=告警阻断；读 load_dq_rules=**dq.json 优先**/旧 ts.dq_rules 兜底[2026-09-14 DQ 拆分]；报告 DQ 段带 mode 分列+对比式 0 行双义提示+ALERT 三选一分流文案）** → 报告，分钟级） | 步骤 6b | ts.json + etl/ + ddl/ + dq/ + dq.json → ut_report.md / `_internal/ut_sql/{rule}.sql` | **ts.rules + ts.init.rules**（init 先建基线→增量在基线上 merge；prev_failed 跨阶段级联；DQ 规则读 dq.json） |
| `run_ut.py` | **UT 函数库**（wrap_insert / wrap_write / run_ut_check / **run_dq_checks（DQ 执行：COUNT 判行数+告警采样；条目透传 mode/waived[2026-09-14]**） / **dq_filename（DQ 文件确定名 dq_{NN}_{清洗check_type}.sql 单点——序号消重名，assemble_dq 派生校验与 UT 找文件同源；slice_ts --dq 已退役不再是消费者）** / **load_dq_rules（DQ 规则双源读取[2026-09-14]：build/dq.json 优先，旧 ts.dq_rules 兜底[存量兼容，条目补 mode=assertion]）** / substitute_params / resolve_all_params 等，被 ut_precheck/ut_execute import。纯函数库无 CLI 入口——UT 执行走 ut_precheck（6a）+ ut_execute（6b）两阶段。**INSERT/MERGE 列清单=结构源**[2026-09-11]：_resolve_insert_columns 从 ts.tables.{目标表}.fields 取序（=装配序=切片序），不再从 SELECT 文本解析——内网实证 CTE 体 `as rn` 被误抓进列清单炸批；列序一致性归 6a describe 对账守；结构源空/重复列 ValueError fail-visible） | 函数库：ut_precheck/ut_execute 用 | （由调用方读 ts） | 由调用方决定（ut_execute 读 ts.rules + ts.init.rules + dq.json） |
| `ut_diagnose.py` | UT 类型转换失败自动诊断（`diagnose_type_error`：圈跨类型字段→探测源表脏值+样例）+ **报错分类 + 关联键嫌疑反查 + 嫌疑报告**（classify_db_error 只认高置信模式宁漏诊不误诊；diagnose_join_suspicion 用 ts joins×schema_cache 列跨大类对；路由建议：有 join 嫌疑退 designer/人禁改类型）。ut_execute 钩子调用；CLI 供复跑（`--ts --rule`） | ut_execute 钩子调用 / designer·coder 复跑 | ts.json → 嫌疑报告文本 | ts.tables[].fields + ts.rules[].joins + ts.rules[].source_tables + `_internal/schema_cache.json` |

### legacy 校验
> 已删除（2026-08 清理）：`sql_validator.py` / `validate_ddl.py` / `verify_files.py` / `lib/dws_preprocessor.py`（仅被已删的 validate_sql 引用，零生产引用零测试）。`CLAUDE.md` / `eval-suite/idle-task-prompt.md` 里还有提及，那两份是已知滞后文档，不再同步。

---

## ② designer agent 调用（设计子 agent 内部，住 dws-design）

| 工具 | 干啥 | 何时调 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------|------------|-------------------|
| `assemble_ts.py` | rs_input + design_decisions → ts.json + ts.md；跑 ~40 条校验（五层+LI，含 **N_JOIN1 关联键类型闭合**：rs_input._join_type_risks 检出对必须 joins.cast 或豁免） | designer 写完 decisions 后组装 | rs_input.json + design_decisions.yaml → ts.json / ts.md | 读 decisions.rules **+ decisions.init**（Chunk 1 已接通 init 段） |
| `explore.py` | **评估层作业台两步（2026-09-17）**：`--plan` 从 rs_input 拉清单草稿（结构化条件预填键/限定[parse_join_pairs 复用]、自然语言留 ? 并排原文、取一/最新免实测分流[rn=1/关键词，SQL 开窗 partition by vs 关联键机械核对]、precheck 已核/存疑标记带出）+ `--batch-stdin` 行协议 `别名\|键\|限定`（别名经 rs_input 反解；**stdin 通道**——argv 内联 JSON 已退役[PS 5.1 剥双引号+'N' 字面量与 JSON 定界符同形无解]，bash heredoc/PS here-string 逐字透传引号免疫）跑存在性闸（schema_cache，键字段不存在→不跑唯一性直接疑点+相近名线索）+唯一性实测（COUNT/COUNT DISTINCT+重复组样例，复合键支持），出三段结果单（逐行结论/join_safety 事实行可直贴/疑点草稿）。单查 --check-join-key=engineer 定向验证；--check-overlap 键值重叠率（双侧采样500 算交集）保留；--batch 收 YAML/JSON 文件（engineer）。数据源锚点 **--rs（设计期）** > --ts > --schema | designer 评估层取证（两步各一次封顶）/ engineer 定向验证 | rs_input.json + stdin 行 → 三段结果单 | 读 rs_input.source_tables/_db_verified/_condition_issues + schema_cache |
| `assemble_ts_opt.py` ★opt | 优化模式组装：ts_baseline + 增量 decisions（opt-decisions-template.yaml）→ ts_v2 + ts.md + change 段；validate 含引用门禁（N36 等价）+ 新 JOIN 键类型比对（N_JOIN2 等价，cache 门控跨大类须 cast）；确定性应用不动存量；_baseline（含 provenance）透传 | 优化模式 designer 写完 decisions 后 | ts_baseline.json + decisions.yaml → ts_v2.json + ts.md | 读 ts_baseline 全部 + 写 change 段 |
| `check_field.py`（★ designer 自有入口，**定位收窄 2026-09-17**：引用确认器——写口径确认引用字段存在/类型+第4层②类型兜底；评估层例行已归 explore 作业台） | 字段查证：抄正要写的 `别名.字段` 引用直接查 schema_cache（别名自动解析；查无给相似字段建议=找准确名帮手，**不是替换依据**；只给别名=列全表）。内核调 shared/schema_query | designer 写 design_logic 引用 mapping 外字段前；惯例假设字段（SCD2 start_date 类）先查再写 | rs_input.json + 别名.字段 → 存在性/类型/相似建议 | 不读 ts（读 `_internal/schema_cache.json`） |
| `pick_targets.py` | designer 字段清单取料器（类比 coder 的 pick_fields）：rs_input → yaml 最终格式片段（--targets 清单 / --rule 规则条目骨架判断位留空；--scenario/--alias/--audit 过滤）——誊写归工具判断归人，贴入零调整 | designer 写 decisions 随用随查 | rs_input.json → stdout 片段 | 不读 ts |
| `schema_query.py`（住 design-dev-shared，**能力层**：query_fields/lookup_table 库 + 通用 CLI） | 字段查询公共能力——check_field（designer 入口）/ pick_fields（coder 入口）的内核 | 被两个角色入口 import；通用 CLI 仅兜底 | 锚点 + schema.table → 存在性/字段清单 | 不读 ts（读 `_internal/schema_cache.json`） |

---

## ③ coder agent 调用（编码子 agent 内部，住 dws-coding）

| 工具 | 干啥 | 何时调 | 输入 → 输出 | 读 ts[rules/init] |
|------|------|--------|------------|-------------------|
| `slice_ts.py` | 切单规则上下文为 YAML（fields 三桶直出；normalize_ts 兜底旧结构）；**--dq 已退役**[2026-09-14 DQ 拆分——DQ 切片入口=pick_dq_context，DQ 不再走 coder]；`--baseline-sql` 切**优化模式**（带 baseline SQL 原文+落位声明+硬约束，加法扩展零动存量路径） | coder 每规则起手 | ts.json + rule_code [+baseline-sql] → YAML 切片 | **ts.rules + ts.init.rules**（查两处；derive init 切片带 clone_source：源 .sql + filter/init_filter；opt 模式读 ts.change） |
| `pick_fields.py` | 直取字段查询（list/**alias 单个或逗号分隔多个**/**all-direct 全部直取一次取按表分组**/field/table-fields）；import slice_rule；`--table-fields` 的查缓存能力来自 shared/schema_query 库 | coder 写直取字段时 | ts.json + rule_code → 字段行；读 schema_cache.json | **ts.rules + ts.init.rules**（随 slice_ts 接通 init） |
| `check_sql.py` | coder 的 SELECT vs ts 切片静态对比（字段覆盖/FROM 表/schema 前缀/CTE 投影一致性/**字段存在性三层核对**（schema_cache 源表/ts tmp 字段/CTE 已另查）/**口径引用对账**（design_logic 限定引用 ⊆ SQL 引用，漏实现当场抓）/**表达式口径对账**（design_logic 的 case when 归一化后应原样出现在 SQL——防 coder 演绎改口径；不匹配**归提示级不阻断**，闸口②人工核对）/括号引号/无 SELECT *）；--dq 模式已退役（2026-09-15 校验合并：检查项并入 assemble_dq 的 N_DQ10，DQ 唯一校验入口） | coder 写完自检 | SELECT.sql + ts.json + rule_code → PASS/FAIL | **仅 ts.rules**（Chunk 2）+ **§5 投影列序对账**（2026-09-15：extract_top_projection vs ts.tables 结构源序——按位 INSERT 乱序=静默错位数据，前移 6a describe 才能发现的错位到 coder 写完即拦；旧形态 tables 空跳过） |

---

## ④ imported（非直接调用，被上述脚本 import）

| 模块 | 干啥 | 被谁 import | 所在 |
|------|------|------------|------|
| `dws_db.py` | DB 连接抽象（DBExecutor + PsycopgExecutor）+ diagnose_connection | precheck / ut_precheck / ut_execute / check_db | design-dev-shared/scripts |
| `type_compat.py` | 类型兼容判断（assess_type_risk + RISK_LABEL_CN + parse_type_info；字符类型互跨 nvarchar↔varchar 等报 charset_semantics 人工决策，不自动放行）+ **join_key_pair_risky**（JOIN 键对保守谓词：跨大类风险，integer↔numeric/同族放行） | precheck / ut_diagnose / assemble_ts(N_JOIN2) | design-dev-shared/scripts |
| `run_ut.py` | UT 函数库（wrap_write / run_ut_check / 参数替换 / INSERT 列重复终检 / dq_filename / load_dq_rules） | ut_precheck / ut_execute / ut_opt / artifact_patcher / sql_fence_check / assemble_dq | design-dev-shared/scripts |
| `sql_parse.py` | SQL 文本解析原语（read_sql / split_cte_main / parse_cte_bodies（均字符串字面量感知）/ extract_select_aliases / extract_from_tables / extract_table_refs_raw / cte_projection_names / extract_qualified_refs / extract_condition_field_refs / find_field_provenance / is_trivial_assign_detail / extract_case_when_exprs+norm_expr（表达式口径对账的提取原语，词边界防误匹配）/ parse_join_pairs / extract_logic_refs / find_unqualified_refs（N36 守门原语，剥全角括号说明段；known_fields 豁免参数[2026-09-11]——已登记自建/派生字段裸引用放行）/ find_three_part_refs（三段式引用硬拦原语——N36/N30/N_DQ5 共用；两两配对提取对 x.y.z 恰好漏掉字段本身，须前置拦）/ **normalize_logic_line**（design_logic 落盘单行归一，引号串保护） | run_ut / check_sql / precheck / assemble_ts(N30/N36/N_JOIN2) | design-dev-shared/scripts |
| `dws_standards.py` | 审计字段标准常量（STANDARD_AUDIT_TEMPLATE） | assemble_ts / precheck | design-dev-shared/scripts |
| `lts_task_paths.py` | LTS 调度任务路径解析（load_schedule_config 读 lts_config 任务路径段 + resolve_schedule_path 按 schema×任务种类[f/view/dq/init]两维度嵌套解析）——2026-09-14 自 assemble_ts 抽出（assemble_dq 建 dq 任务同款解析，两消费者归 shared） | assemble_ts（re-export 保旧名）/ assemble_dq | design-dev-shared/scripts |
| `ts_compat.py` | ts 结构兼容层：classify_field 分桶原语 + normalize_ts 旧结构内存升级（幂等，认远古 rule.fields-only）——两视图重构后读旧 ts 的下游全走此路 | slice_ts / check_sql / assemble_export / fence_check / assemble_ts / assemble_ts_opt | design-dev-shared/scripts |
| `baseline_contract.py` ★opt | baseline_v1 契约消费端校验器（vendored JSON Schema + 版本支持 1.0/1.1 + dm=6 必 merge_on 语义检查） | assemble_ts_baseline / tests/test_baseline_v1_contract | skills/opt-pipe/scripts（schema 在 opt-pipe/schemas） |

---

## ⑤ 优化场景 opt-pipe 调用（专用节，2026-09 归位：全部住 skills/opt-pipe/scripts + schemas，对存量零接触）

> 设计定稿见 `docs/specs/opt/00-08` + `docs/architecture/opt-架构设计.md`。分阶段实施（08 §七）：阶段一零存量接触，阶段二动四个接触点（评测闸门后）。本节随实施进度登记。

| 工具 | 干啥 | opt-pipe 阶段 | 输入 → 输出 | 状态 |
|------|------|--------------|------------|------|
| `opt-pipe/schemas/baseline_v1.schema.json` | 契约 vendor 拷贝（权威在 analyzer 仓） | 步骤 0 入料 | baseline_v1.json 的校验基准 | ✅ 阶段一 |
| `baseline_contract.py` | 契约校验（schema+版本+语义条件） | 步骤 0 入料 | baseline_v1.json → 违规清单 | ✅ 阶段一 |
| `assemble_ts_baseline.py` | json 入料建档：档案件（ts.json + etl/{rule}.sql）落 archive/、过程件（baseline_view + exemptions）落 opt/_internal/；provenance 落 ts._baseline；kind→load_mode 映射、词表外待定不硬映射 | opt 步骤 0 入料 | baseline_v1.json → archive/ + opt/_internal/ | ✅ |
| `preprocess_opt.py` | **现场就绪**（清场重建 build/ 增量现场 + cp archive→archive_tmp 临时档案）+ 标注解析 → change_request + 一致性校验（冲突/漏标/配对/资产一致[I/F 镜像归一]/RS 对账 warn）；契约参数直传 --mapping/--rs | opt 步骤 1 | mapping xlsx + RS md + archive/ts.json → build/_internal/change_request.json | ✅ |
| `precheck_opt.py` | 步骤 1b 优化预检（只检新增子集）：命名规范/连库存在性+类型对账（以库为准回填）/类型风险决策（回写 fields『decision』标记）/值域探测/新来源 JOIN 键对账；复用 shared 原语（risk_checks/schema_cache）；无库降 warn | opt 步骤 1b | change_request + archive/ts.json → 决策回写 change_request + PENDING 摘要 | ✅ |
| `gate_summary_opt.py` | 闸口①'材料确定性产出（逐字段落位表/新 JOIN/决策标记/回刷/预检汇总——不 AI 摘要） | opt 步骤 3 | ts_v2 + baseline + change_request → gate_summary_opt.md | ✅ |
| `diagnose_fanout_opt.py` | opt 关联发散定位（逐表键唯一性主判据 + join_safety 断言对照 + 重复键样例；轻量版——不做 join-count/解剖） | opt 步骤 5 对比 FAIL 后 | ts_v2 → diagnose/fanout_{rule}.md | ✅ |
| `sql_fence_check.py` | SQL 围栏 CLI（pipe 独立跑；逐 placed_rule 比对；opt 新 SQL 与档案同名；**结果落盘 sql_fence_result.json 供 ut_opt 时效闸门**） | opt 步骤 4 后 | opt/ts_v2 + opt/etl + archive/etl → FENCE_PASS/违规清单 + _internal/sql_fence_result.json | ✅ |
| `ut_opt.py` | 优化 UT 独立入口（**围栏时效闸门**[SQL 晚于围栏结果拒跑] + ALTER[缺失 fail loud] + 每规则 EXPLAIN ANALYZE 两门槛落盘 + **行数对账**[裸 COUNT 不等=发散/丢行硬信号] + 双向 MINUS 对比 + INSERT 全量 + 新列空值检查 + **DQ 段**[2026-09-14 补环：对比/INSERT 全过后自动真跑——重做条目上生产前必须执行验证；load_dq_rules 读 arc_tmp 的 dq.json/旧 ts.dq_rules 兜底；ALERT 阻断出口归闸口②' 人判三选一，报告带对比式 0 行双义提示]；零触碰 ut_precheck/ut_execute） | opt 步骤 5 | ts_v2 + opt/etl + archive/etl + opt/ddl + arc_tmp dq → ut_report_opt.md | ✅（DQ 规则读 dq.json） |
| `dq_impact.py` | ★**DQ 影响分析**（2026-09-14 DQ 拆分补环，步骤 3.5）：变更集 ∩ baseline DQ 锚定的确定性集合运算（变更目标字段∩anchored_fields / 变更来源表∩compare_sources）→ 重做清单（producer 只重做受影响条目，未受影响原样继承）；旧形态兜底（无锚定声明时从 violation_condition 粗提；baseline 无 DQ=空清单不算错）；清单进闸口①'材料——"DQ 变更恰好=重做清单"（影响分析是围栏的 DQ 版本） | opt 步骤 3.5（precheck 后、闸口①'前） | baseline dq.json[或旧 ts.json] + change_request.json → 重做清单 md | 读 baseline dq.json 的 anchored_fields/compare_sources |
| `assemble_ddl_opt.py` | ALTER 变更单 + **I 视图重建 DDL**（generate_i_view 单源——F 表加列后镜像同步）+ ts diff 审计（全量 DDL 已退役：ts 的可再生投影不入交付不入档案） | opt 步骤 5（先于 UT） | ts_v2 + archive/ts.json → opt/ddl/ | ✅ |
| `artifact_patcher.py` | 制品 patch 引擎（xlsx TargetFields 行追加+SQL 单元格替换 / yml 组 round-trip；严格 patch 不碰漂移；patch 说明）；--source 从 ts_v2._baseline.provenance 定位、取不到问人 | opt 步骤 6 | ts_v2 + opt/etl + 原始制品 → opt/export/patched + patch_notes | ✅ |
| `archive_writer.py` | 档案两动作（子命令，**住 shared**——new-pipe 收尾+opt 收口双消费者）：`adopt` 交付建档（new-pipe 闸口②确认后：从 build/ 提取本源件 ts/etl/dq/**ddl**/export/decisions 生成 archive/ + MANIFEST 首建）/ `advance` **三步全量替换**（archive_tmp 整体上位为 archive；替换前清 tmp 过程产物+MANIFEST 追加；崩在任意一步可恢复） | new-pipe 步骤 8 / opt 步骤 7 | adopt: build/ → ../archive/；advance: archive_tmp/ → archive/ | ✅ |
| `fence_check.py` | ts 级围栏（声明驱动比对：diff 分解 + add_field 冻结/许可矩阵 + 恰好等于双向判定；定义 ts.change 段消费形状） | opt 步骤 3 | archive/ts.json + opt/ts_v2.json + change_request → FENCE_PASS / 越界+漏改清单 | ✅ 阶段一 |
| `sql_fence.py` | SQL 围栏判定纯函数库（AST 老列逐列结构等价/仅追加声明列/JOIN·WHERE·GROUP BY 冻结/不支持形态转人工；rule_declaration 从 change 段派生单规则许可） | 步骤 4（pipe 独立跑；check_sql 可选自测共用） | baseline SQL + 新 SQL + 规则声明 → 违规清单 | ✅ |

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

derive 模式 init SQL：**不**用脚本字面派生——改由 coder 适配（slice_ts 带 clone_source，coder 读源 .sql 改 filter）。code 归 coder。
