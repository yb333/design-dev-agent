# 交接文档

> 本文档是会话间的交接。新会话先读 `AGENTS.md`（项目约定速查）+ 本文档（当前进度和结晶）。
> 起始：2026-08-07

---

## 一、这个项目是什么

设计开发 Agent——数据仓库 ETL 的设计开发段。输入 mapping（字段映射）+ RS（需求spec，可选），输出 TS 制品包（ts.json/ts.md）+ 四件套制品（DDL/术加ETL/LTS调度/DQ）。

一个 agent 连续完成「设计 → 编码 → UT」，中间有闸口①（设计确认）和闸口②（编码确认）。

**入口文档**：`AGENTS.md`（项目约定速查）→ `commands/new-pipe.md`（唯一编排剧本）。

---

## 二、本轮会话干了什么（按时间线）

### 1. 评测体系优化 + UT 失败回路
- **UT 失败三类分流**（new-pipe.md 步骤7）：SQL问题→coder改语法；数据质量问题→退回designer（不让coder用ROW_NUMBER掩盖症状）；环境问题→报告人。
- 退回designer时带"精简依据包"（失败项+样例 / coder实际SELECT / join_safety / business_key）。
- run_ut_check 加 LIMIT 捕获主键重复/空值样例。
- 预检结果文件归到 `_internal/`，读不到 fail loud。

### 2. rs_input.json 瘦身（compact 视图）
- **问题**：156KB 的 rs_input.json 让 designer 上下文爆炸（57% 是 JSON key 名重复）。
- **方案**：preprocess 产双文件——`rs_input.json`（完整给脚本）+ `rs_input_view.json`（compact分块视图给designer，省70%）。
- **格式决策**：用 JSON 不用 Markdown（业界验证 json 往返保真度高于 md，避免文本化失真）。compact 三段：tables（表级清单）/ direct（直取按表分块）/ processed（加工逐字段平铺）。多场景NULL字段跳过+标记。
- **独立文件决策**：原本设计成单文件双块，但 Read 工具读全文——compact 独立成文件让 designer 只读 23KB 不读全文 120KB。

### 3. ts 多步骤数据流模型（核心架构成果）
- **问题**：增量设计"低级死板"（单表WHERE过滤），根因在 ts 规则模型——一个rule只能产一个表、跨rule依赖靠数字隐式、load_mode表级。
- **业界调研**：临时表+MERGE是共识（Skyvia/Databricks/Fabric三篇一致）；CTE vs物化有五条标准（多次引用/估算偏差>10x/大数据/检查点/跨步骤，真实案例90min→15s）。
- **实践确认**：增量全量各半；多驱动表各自增量；物理临时表每次重建；MERGE用business_key；合并方式看表类型。
- **方向A落地**：rule 加 step_type（full/aggregate/incremental_extract/merge）+ target_role（intermediate/target）+ produces_for/reads（依赖声明）。简单全量走full老路不受影响。
- **三层嵌入**：design-guide §4.4（step_type决策树+CTE五条标准）+ §5.2（多源增量设计）重写；SKILL.md 设计流程改（增量识别提前到步骤3）；designer.md 补增量/复杂度审视。
- **字段分配校验修复**：validate_decisions 从"全局唯一"改为"按表归属"——同字段可跨表（中间表+目标表各一份），同表内重复才报错。

### 4. 写入配置承载（write_condition）
- **问题**：MERGE的ON条件/partition分区名/delete的WHERE无处承载；run_ut只会拼INSERT；export删除模式硬编码"1"。
- **关键决策**：统一designer填不做推导（用户洞察：复杂的能填对简单的更不在话下，半推导增加系统复杂度）。
- **六处落地**：ts-template加write_condition字段；assemble_ts搬运+校验（非空/非中文）；run_ut新增wrap_write（按load_mode拼INSERT/MERGE，目标表别名T源T1）；ut_execute预处理分流；assemble_export从load_mode映射删除模式；coder.md补step_type感知+etl-templates加增量取数/读tmp合并模板。

### 5. 闲时任务（5个，全部落地）
- 任务一：preprocess 解析 RS 增量表段 → schedule.incremental_tables
- 任务二：assemble_ts 组装 step_type/target_role/produces_for/reads 进 ts.json
- 任务三：explore.py（designer试算JOIN键唯一性，复用dws_db）
- 任务四：调度路径（project/task_group）进 ts.json（schedule_config）
- 任务五：单元测试覆盖缺口排查（+100测试，gate_summary/pure_funcs/explore等）

### 6. 预处理/预检鲁棒性
- **RS解析错误报告**：extract_rs_data 之前收集了errors/warnings但main静默吞掉。现在main打印+exit(1)。区分三种失败：段缺失/段在但表格没解析出/段在但核心字段丢。
- **增量校验**：precheck 新增5b段——标了增量必须有驱动表+增量字段，驱动表须在source_tables里。
- **无RS模式**：正式支持mapping独立驱动核心链路（--rs可选），schedule用默认值兜底，_no_rs_mode标记，precheck给warn不阻断。

### 本轮会话续（2026-08-11）：init 双管道 + 工程治理 + config/目录分层 + 编排者铁律

**1. init 双管道模型（设计侧 + 下游物化，全链路通）**——修掉增量目标 load_mode=truncate 全删全插的致命 bug。
- 根因：一个 rule 一个 load_mode 装不下 init/增量两种写入。改双管道：增量管道(`rules`,merge 等)+ init 管道(`init` 段,恒 truncate_table)。
- 设计侧：`build_init_section` 装配器(7 不变量补全 + core_from 抄口径)+ LI 层校验(N_INIT1/2/3/4 + mode/group_mode)。derive(无 delta 机器,克隆增量物化)/ explicit(有 delta 机器,designer 写)。group_mode:inline(同组 P_FLAG)/ separate(独立任务)。
- 下游物化：slice_ts 查 ts.init.rules + derive 带 clone_source(源 SQL+filter,coder 适配写 INIT.sql,**不用脚本派生**);export 发 init 行(inline P_FLAG/separate 任务+计数);ut **init 先建基线→增量后 merge**(符合现实部署顺序)。
- 全过程见 incremental-playbook §八。非破坏(无 init 资产不受影响)。

**2. 工程治理：工具注册表 + agent 瘦身 + legacy 清理**
- `docs/tool-registry.md`：全脚本按**调用方**分组(command/designer/coder/imported)，含"读 ts[rules/init]"进度列。约定：改脚本必同步注册表。
- dws-designer.md(197→85)/dws-coder.md(112→65) 瘦身：工作流削回 SKILL.md 指针(消灭双写)，分层定型 tool-registry/agent.md/SKILL.md。
- 删 sql_validator/validate_ddl/verify_files(零引用死代码+孤儿测试)。assemble_dq(eval-suite 在调)/run_ut(UT 函数库)保留，整改挂闲时任务六。

**3. config 集中 + 产出目录加 appid/schema 层**
- `config_paths.py`(design-dev-shared)：config_dir() 集中，改基址只动一处。4 个 config 统一放 `~/.config/opencode/_references/rules/dws-design-dev/`(与其他项目隔离)。
- 产出目录改 `10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/`。appid 单源 = 新 `schema_apps.json`(**appid 打头,1 appid 多 schema**)+ resolve_appid。platform_config 去掉 appid。⚠️ 部署：老位置不兼容，重跑 install.py + 手搬老 db-sources.json。

**4. 编排者铁律**（new-pipe.md 顶部）：跑 pipe 的子 agent 故意不定义(免得 designer/coder 变第三层)，靠 new-pipe.md 扛——显式忽略 caller 传入的"自动修正/重试"垃圾指令(不 author 脚本、校验失败按路由不自动修)。管不着 caller 怎么写，管自己内容的规矩。

---

## 三、关键结晶（继任者必须知道的）

### ts 多步骤数据流模型（最重要的架构成果）

这是本轮的核心。ts.json 的 rule 现在有完整的步骤类型和依赖声明：

```
R0001: aggregate         → tmp1   (intermediate, produces_for=[R0003])
R0002: aggregate         → tmp2   (intermediate, produces_for=[R0003])
R0003: full              → 目标表 (target, reads=[tmp1,tmp2])
```
或增量：
```
R0001: incremental_extract → tmp_a (intermediate, produces_for=[R0003])
R0002: incremental_extract → tmp_b (intermediate, produces_for=[R0003])
R0003: merge              → 目标表 (target, reads=[tmp_a,tmp_b], load_mode=merge_into, write_condition="T.id=T1.id")
```

**决策权威**：design-guide.md §4.4（step_type决策树+CTE五条标准）+ §5.2（多源增量设计）。

### 写入配置（平台规范）

| load_mode | delete_mode | write_condition | 谁填 |
|-----------|------------|-----------------|------|
| truncate_table | 1 | 空 | 不用填 |
| no_delete | 2 | 空 | 不用填 |
| truncate_partition | 5 | 分区名（P_1001）| designer |
| delete | 4 | 删除WHERE（rule_id>0）| designer |
| merge_into | 6 | ON条件（T.id=T1.id）| designer |
| update | 6 | ON条件 | designer |

目标表别名 T，源别名 T1。统一 designer 填不做推导。coder 只写 SELECT，写入动作由平台配置 + run_ut 的 wrap_write 拼接。

### RS vs mapping 职责边界

- **必须从RS**：目标表schema.table、调度/增量/DQ、湖表调度、数据探索、粒度/owner
- **mapping就够**：字段映射主体（占90%+体积）、源表清单
- **无RS模式**：mapping独立驱动核心链路，schedule用默认值兜底，90%场景建议有RS

### rs_input 双文件

- `rs_input.json`（完整，脚本读）+ `rs_input_view.json`（compact分块，designer读，省70%）
- designer 用 Read 读 view（23KB）不读 input 全文（120KB）

---

## 四、文档地图（每个文档干什么）

| 文档 | 作用 | 状态 |
|------|------|------|
| **AGENTS.md** | 项目约定速查（新会话入口） | ✅ 已是最新 |
| **HANDOFF.md** | 本文档（会话交接） | ✅ 本次新建 |
| **commands/new-pipe.md** | 唯一编排剧本（设计→闸口①→编码→UT→闸口②）| ✅ 已是最新 |
| **agents/dws-designer.md** | designer 岗位（身份+权限+skill指针+工具清单，工作流在 SKILL.md）| ✅ 已瘦身 |
| **agents/dws-coder.md** | coder 岗位（身份+权限+工具清单，工作流在 SKILL.md）| ✅ 已瘦身 |
| **skills/dws-design/SKILL.md** | designer 设计流程（五层决策骨架 + §2.5 关联决策）| ✅ 已是最新 |
| **skills/dws-coding/SKILL.md** | coder 编码流程（五步 + §2.5 init 规则编码）| ✅ 已是最新 |
| **skills/dws-design/references/incremental-playbook.md** | 增量设计全集（§八 init 双管道模型 + derive/explicit + 装配器）| ✅ 已是最新 |
| **skills/dws-design/references/design-guide.md** | 物理决策（分布键/分区/依赖类型）| ✅ 已是最新 |
| **skills/dws-design/assets/ts-template.json** | ts.json结构权威定义（含 init 段）| ✅ 已是最新 |
| **skills/dws-design/assets/design-decisions-template.yaml** | designer产出骨架（含 init 段）| ✅ 已是最新 |
| **skills/dws-coding/assets/etl-templates.md** | SELECT模板（含增量取数/读tmp合并）| ✅ 已是最新 |
| **docs/tool-registry.md** | 全管线脚本注册表（按调用方分组 + 读 ts[rules/init] 进度列）| ✅ 本次新建 |
| **skills/design-dev-shared/scripts/config_paths.py** | config 路径集中（config_dir + resolve_appid，改基址只动一处）| ✅ 本次新建 |
| **docs/architecture/incremental-design-discussion.md** | 增量/ts设计讨论全记录（含调研+实践+方案）| ✅ 第十节全勾完 |
| **CLAUDE.md / README.md** | ⚠️ 滞后（仍描述旧dws-pipeline-*结构），以AGENTS.md为准 | ❌ 待更新 |

---

## 五、下一步可做的事

### 待讨论（未定方案）
- **coder 按 step_type 产不同 SQL 的实际验证**：coder.md 和 etl-templates.md 已补引导，但还没拿真实增量资产跑过全链路验证（designer产design_decisions含step_type → coder产SELECT → run_ut的wrap_write执行）
- **UT 按 produces_for/reads 编排执行顺序**：现在靠 schedule_groups 隐式数字排序，多步骤的显式依赖没用于执行编排
- **platform_config.lts 的 project_name/task_group 跟 schedule_config 冗余**：新 ts.json 不用 lts 兜底，可清理（platform_config 本身的 shujia 段删不掉，export 要用）——待讨论
- **闲时任务六**（`eval-suite/idle-task-prompt.md`）：assemble_dq 退役（eval-suite 改走 coder 生成 DQ 后删）/ run_ut 去 legacy（函数库 vs main 拆分）

### 验证类
- 拿 test_ai_emp 下的 mapping 文件按 RS 模板重建，跑全链路验证（用户之前提过）
- 无RS模式拿真实 mapping 跑一遍（preprocess→precheck→assemble_ts）
- **init 双管道真实验证**（2026-08-11 新增，重点）：拿真实增量资产跑一遍——designer 产 init 段(derive/explicit) → coder 写 INIT SQL → export 出 init 执行行 → UT init 先建基线跑通。设计侧+下游物化都是单测覆盖，真实验证还没做。
- **config 新位置 + appid 目录层真实验证**：有真实 db-sources 的机器重跑 install.py，手搬老 db-sources.json 到 `_references/rules/dws-design-dev/`，跑一次 new-pipe 验 appid 解析 + 新目录结构 + config 新位置读取都通。

### 维护类
- CLAUDE.md / README.md 更新到当前实际结构（仍描述旧的 dws-pipeline-* 9-skill）

---

## 六、测试现状

**669 测试全过，2 skip（psycopg2 未装）**（2026-08-11）。本轮新增覆盖：
- test_assemble_ts.py：init 装配器(derive 物化/explicit 不变量/core_from 抄口径)+ LI 校验(N_INIT1/2/3/4 + mode/group_mode)+ tasks["init"]/P_FLAG + 两管道写同表
- test_coding_scripts.py：slice_ts init 规则查找 + derive clone_source(源 SQL/filter)
- test_pure_funcs.py：resolve_appid(appid 打头多 schema 反查 + default 兜底)
- 其余既有覆盖不变：test_preprocess（build_compact/无RS/增量表）/ test_precheck_db（连库/类型/增量）/ test_coding_scripts（wrap_insert/wrap_write 五种 load_mode / run_ut_check 样例）/ test_assemble_export（init 行 + 调度路径 + appid 注入）/ test_explore / test_gate_summary。

---

*继任者：先读 AGENTS.md 了解约定，再读本文件了解进度。所有文档都是最新的（除CLAUDE.md/README.md滞后）。有疑问看 incremental-design-discussion.md 的讨论全记录。*
