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
| **agents/dws-designer.md** | designer角色认知（主键/关联/增量/复杂度/数据质量诊断）| ✅ 已是最新 |
| **agents/dws-coder.md** | coder角色认知（step_type感知、只写SELECT）| ✅ 已是最新 |
| **skills/dws-design/SKILL.md** | designer设计流程（9步，增量识别提前到步骤3）| ✅ 已是最新 |
| **skills/dws-design/references/design-guide.md** | 领域知识（§4步骤拆分/§5调度增量/含CTE五条标准+step_type决策树）| ✅ 已是最新 |
| **skills/dws-design/assets/ts-template.json** | ts.json结构权威定义 | ✅ 已是最新 |
| **skills/dws-design/assets/design-decisions-template.yaml** | designer产出骨架 | ✅ 已是最新 |
| **skills/dws-coding/assets/etl-templates.md** | SELECT模板（含增量取数/读tmp合并）| ✅ 已是最新 |
| **docs/architecture/incremental-design-discussion.md** | 增量/ts设计讨论全记录（含调研+实践+方案）| ✅ 第十节全勾完 |
| **CLAUDE.md / README.md** | ⚠️ 滞后（仍描述旧dws-pipeline-*结构），以AGENTS.md为准 | ❌ 待更新 |

---

## 五、下一步可做的事

### 待讨论（未定方案）
- **coder 按 step_type 产不同 SQL 的实际验证**：coder.md 和 etl-templates.md 已补引导，但还没拿真实增量资产跑过全链路验证（designer产design_decisions含step_type → coder产SELECT → run_ut的wrap_write执行）
- **UT 按 produces_for/reads 编排执行顺序**：现在靠 schedule_groups 隐式数字排序，多步骤的显式依赖没用于执行编排

### 验证类
- 拿 test_ai_emp 下的 mapping 文件按 RS 模板重建，跑全链路验证（用户之前提过）
- 无RS模式拿真实 mapping 跑一遍（preprocess→precheck→assemble_ts）

### 维护类
- CLAUDE.md / README.md 更新到当前实际结构（仍描述旧的 dws-pipeline-* 9-skill）

---

## 六、测试现状

**419 测试全过**。测试覆盖：
- test_preprocess.py：build_compact/extract_rs_data/无RS模式/增量表解析
- test_precheck_db.py：连库校验/字段类型/增量校验/无RS模式
- test_assemble_ts.py：validate_decisions（按表归属）/ build_rule（step_type搬运）/ write_condition校验
- test_coding_scripts.py：wrap_insert/wrap_write（五种load_mode）/ run_ut_check（样例捕获）
- test_assemble_export.py：调度路径导出
- test_explore.py：试算SQL参数解析/SQL拼接
- test_gate_summary.py / test_pure_funcs.py：覆盖缺口补充

---

*继任者：先读 AGENTS.md 了解约定，再读本文件了解进度。所有文档都是最新的（除CLAUDE.md/README.md滞后）。有疑问看 incremental-design-discussion.md 的讨论全记录。*
