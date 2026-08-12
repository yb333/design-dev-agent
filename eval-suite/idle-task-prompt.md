# 闲时任务提示词：preprocess 解析增量表 + assemble_ts 组装新字段 + designer 试算 SQL + 调度路径进 ts.json + 单元测试补缺 + legacy 脚本整改

> 用于空闲时段执行。复制下面的提示词给 agent，在项目目录下执行。
> 五件事**有顺序依赖，按编号顺序做**（后面的改动覆盖前面的产出物）：
> - 任务一（preprocess 解析）产出 rs_input.json → 任务二（assemble_ts 组装）消费它
> - 任务二改 assemble_ts → 任务四（调度路径）也改 assemble_ts，二先做避免冲突
> - 任务三（试算 SQL）改 design-decisions-template，在二之后（二不动 join_safety）
> - 任务五（单测补缺）必须最后做，覆盖前面所有改动的新代码

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：preprocess 解析 RS 增量表段

**背景**：RS 模板 L07 已补了"增量表及增量字段"段：
```
**增量表及增量字段**
| 来源表 | 增量字段 |
|--------|---------|
| xxxx.xxxx | xxxx |
```
但 preprocess.py 的 extract_rs_data 不解析这段——designer 拿不到结构化的
驱动表信息（只能靠读 RS 原文）。要把这段解析进 rs_input.json。

**这是第一个任务的原因**：preprocess 产出 rs_input.json，是整条链路的源头。
assemble_ts（任务二）和 designer 都消费 rs_input.json，所以解析逻辑要先就位。

**先读这些理解上下文**：
- `docs/templates/RS模板.md` 的 L07 段（看"增量表及增量字段"段的格式）
- `skills/dws-design/scripts/preprocess.py` 的 `extract_rs_data` 函数（看现在怎么解析 RS 的其他段，如 L07 调度设计、湖表调度）
- `skills/dws-design/references/rs-input-format.md`（看 rs_input 的格式规范，确定增量信息放哪个段）
- 一个真实的 rs_input.json（如 10_project_deliver/dwb_order_center_f/ddlc_design_dev/_internal/rs_input.json 的 schedule 段）

**要做的**：

1. **改 `preprocess.py` 的 `extract_rs_data`**：解析"增量表及增量字段"段表格，提取为：
   ```json
   "incremental_tables": [
     {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
     {"source_table": "ods.ods_payment_f", "incremental_key": "dt"}
   ]
   ```
   - 放进 rs_data 的 schedule 段下（和 incremental_key 同级），或顶层独立段（看现有结构哪个合适）
   - 解析逻辑参照现有 L07 其他表格的解析方式（键值表/列表表的解析模式）

2. **改 `build_rs_input`**：把 incremental_tables 搬进 rs_input.json
   - 放在 schedule 段下（和 strategy/frequency/incremental_key 同级）

3. **改 `build_compact`**（preprocess.py 里那个分块视图）：如果 incremental_tables 非空，在 compact 视图里体现（designer 读 compact 时能看到驱动表和增量字段）

4. **测试**（tests/test_preprocess.py 补）：
   - extract_rs_data 能解析增量表段（构造含该段的 RS 文本）
   - 无该段的 RS（全量资产）不报错，incremental_tables 为空
   - build_rs_input 把 incremental_tables 搬进 schedule 段

**约束**：
- 解析容错：表格格式不标准（缺列、空行）不报错，跳过
- 向后兼容：旧 RS（没有增量表段）正常解析，incremental_tables 为空列表
- 不改 RS 模板（用户已补，不动）

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 对一个含增量表段的 RS 跑 preprocess，确认 rs_input.json 的 schedule 段有 incremental_tables

---

### 任务二：assemble_ts 组装 step_type 等新字段进 ts.json

**背景**：ts 多步骤数据流模型已落地到设计指导（design-guide §4.4）和模板
（ts-template.json + design-decisions-template.yaml 的 rule 内新增了 step_type /
target_role / produces_for / reads 字段）。但 assemble_ts.py 还不搬这些字段——
designer 在 design_decisions 里填了也会被丢掉。这是个断层，要堵上。

**这是第二个任务的原因**：assemble_ts 消费 rs_input.json（任务一产出）和
design_decisions，产出 ts.json。任务四（调度路径）也改 assemble_ts，本任务先做
避免冲突。本任务只改 build_rule 搬字段，不碰 build_meta（任务四改 build_meta）。

**先读这些理解上下文**：
- `skills/dws-design/assets/ts-template.json` 的 rules 段（看新字段的注释和默认值）
- `skills/dws-design/assets/design-decisions-template.yaml` 的 rule 段（看 designer 怎么填）
- `skills/dws-design/scripts/assemble_ts.py` 的 `build_rule` 函数（看现在怎么从 design_decisions 搬字段进 ts.json）
- `skills/dws-design/references/design-guide.md` §4.4（看 step_type 四种类型和依赖声明语义）

**要做的**：

1. **改 `assemble_ts.py` 的 `build_rule` 函数**：从 rule_dec 搬以下字段进 ts.json 的 rule：
   - `step_type`：默认 "full"（designer 没填时）
   - `target_role`：默认 "target"（designer 没填时）
   - `produces_for`：默认 [] （中间表规则才填）
   - `reads`：默认 []（装配/merge 规则才填）
   - 注意：这些字段是可选的，旧 design_decisions 没有这些字段不报错（用默认值兜底）

2. **改 `assemble_ts.py` 的 `render_md`**（如果 ts.md 渲染里涉及规则展示）：
   - 规则表加 step_type / target_role 列（或至少在规则展示里标出来）
   - 中间表规则和目标表规则要能区分

3. **测试**（tests/test_assemble_ts.py 补）：
   - build_rule 搬了 step_type/target_role/produces_for/reads
   - 旧 design_decisions（无新字段）用默认值不报错
   - 有新字段时正确搬入

**约束**：
- 不改 design_decisions 模板（已经加了字段，不用动）
- 不改 validate_decisions（上一轮已改为按表归属校验，兼容多步骤）
- **不改 build_meta**（任务四改 build_meta，避免冲突）
- 保持向后兼容：旧 design_decisions（没有 step_type）跑 assemble_ts 不报错

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 对一个真实资产（如 003_dwb_trade_wide_f）跑 assemble_ts，确认 ts.json 的 rule 里有 step_type 字段

---

### 任务三：designer 试算 SQL（JOIN 键唯一性检查）

**背景**：designer 做 join_safety 分析时，不确定 JOIN 键在右表唯一不唯一——这是"关联会不会发散"的事实依据。RS 只给了关联方式（文字），没给键唯一性（数据事实）。需要给 designer 一个试算手段。

**注意**：只做 JOIN 键唯一性这一个场景。其他数据探索信息（表行数、空值率）RS L01 已提供，不重复。

**这是第三个任务的原因**：本任务改 design-decisions-template（加 join_filter 字段）
和 SKILL.md。任务二也改这两个文件相关的 assemble_ts，但二只搬 step_type 等字段、
不动 join_safety。本任务在二之后做，改的是 join_safety 段和 explore.py，互不冲突。

**核心约束**：
- 复用 design-dev-shared/scripts/dws_db 的 `create_executor_for_schema`，**不重写连库逻辑**（选源/建连/超时/账号全复用）
- 只读（etl 账号），只查单表（不跑 JOIN，不会发散）
- 连不上库静默跳过（和 precheck 一致）
- 不需要采样（单表 count/count(DISTINCT) 不会发散）

**要做的**：

1. **新建 `skills/dws-design/scripts/explore.py`**（设计探索脚本）：
   - 参数：`--ts {ts路径}`（取 target schema 选源）`--check-join-key --schema {sch} --table {tbl} --key {col} [--where "{限定条件}"]`
   - 内部逻辑（复用 dws_db）：
     ```python
     from dws_db import create_executor_for_schema
     executor = create_executor_for_schema(target_schema, role="etl")
     sql = f"SELECT count(*) AS total, count(DISTINCT {key}) AS distinct_cnt FROM {schema}.{table}"
     if where_clause:
         sql += f" WHERE {where_clause}"
     r = executor.execute(sql)
     executor.close()
     ```
   - 输出示例：
     ```
     表 dim.dim_store 的 store_id（限定: is_current = 1）：
       总行数: 141753
       去重数: 141750
       重复数: 3
       结论: ❌ 不唯一（JOIN 此表可能发散，join_safety 需给对齐策略）
     ```
   - `--where` 可选：designer 传 JOIN 时的范围限定（如 `is_current = 1`），验限定后的唯一性
   - 连不上库（无配置/无 psycopg2）→ 输出"无法连库，跳过试算"，退出码 0（不阻断设计）

2. **改 `skills/dws-design/assets/design-decisions-template.yaml` 的 join_safety 结构**：
   ```yaml
   join_safety:
     - table: "dim_store"
       join_filter: "is_current = 1"    # ← 新增：JOIN 此表时的范围限定（来自 mapping 的"关联&限定条件"）
       join_key_unique: true             # 在 join_filter 限定下是否唯一
       strategy: ""                      # 不唯一时的对齐策略
       reason: ""
   ```
   join_filter 字段让 designer 明确写出"JOIN 此表加了什么 WHERE 限定"，explore.py 用它验唯一性。

3. **改 `skills/dws-design/SKILL.md` 步骤 7（关联安全分析）**：
   加引导——"对 JOIN 的非主表，如果不确定键唯一性，调 explore.py 验证：
   `python DESIGN_SCRIPTS/explore.py --ts {deliver}/ts.json --check-join-key --schema {sch} --table {tbl} --key {col} --where "{join_filter}"`
   看结果填 join_key_unique + strategy"

4. **改 `skills/dws-design/scripts/assemble_ts.py`**：join_safety 段组装时保留 join_filter 字段（如果有）。

**约束**：
- explore.py 只做参数解析 + 拼 SQL + 调 dws_db + 格式化输出，连库逻辑零重写
- 加测试：explore.py 的参数解析、SQL 拼接（带/不带 where）、输出格式
- 如有需要，更新 install.py 的 DESIGN_SCRIPTS 路径引用

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- explore.py 能跑（连不上库静默跳过，不报错）
- 如实报告

---

### 任务四：调度任务路径（project/task_group）进 ts.json

**背景**：ts.json 的 schedule.tasks 每个 task 只有 task_name（如 task_xxx_f），没有 project/task_group。
但实际调度中，不同任务（F表/view/dq）和不同阶段（日常/初始化）可能归属不同的项目/任务组。
现在 export 时才从 platform_config 按 schema 取一个固定值，无法表达"初始化和日常不同项目组"。
要把 project/task_group 提前到设计阶段确定，进 ts.json 的每个任务。

**这是第四个任务的原因**：本任务改 assemble_ts 的 build_meta（任务二改 build_rule，
两者改不同函数不冲突，但二先做更安全）。本任务还改 assemble_export，独立于前面的任务。

**核心设计**：
- 新建 schedule_config.json（给 designer 的配置，不是给平台的）
- ts.json 的 tasks 每个任务带 project_name/task_group
- assemble_ts 从 schedule_config 取默认值，designer 可在 design_decisions 覆盖
- render_md 显示完整路径（项目|任务组|任务名）
- export 改为直接用 ts.json 里的 project/task_group，不再从 platform_config 取

**要做的**：

1. **新建 `skills/dws-design/assets/schedule_config.example.json`**（给 designer 的调度配置模板）：
   ```json
   {
     "default": {
       "project_name": "SRP_DAILY",
       "task_group": "GROUP_SPRD"
     },
     "schema_mappings": {
       "fin": {
         "project_name": "FIN_DAILY",
         "task_group": "GROUP_FIN"
       }
     },
     "init_override": {
       "project_name": "SRP_INIT",
       "task_group": "GROUP_INIT"
     },
     "dq_override": {
       "project_name": "SRP_DQ",
       "task_group": "GROUP_DQ"
     }
   }
   ```
   - `default`：按 schema 默认的 project/task_group
   - `schema_mappings`：不同 schema 的默认值
   - `init_override`：初始化调度覆盖（可选，不配就和日常一样）
   - `dq_override`：DQ 调度覆盖（可选，不配就和日常一样）
   - 实际配置放 ~/.config/opencode/schedule_config.json（install 时不覆盖已有，和 db-sources/platform_config 一致）

2. **改 `skills/dws-design/scripts/assemble_ts.py` 的 build_meta**：
   - schedule tasks 的每个任务（f/view/dq）加 `project_name` 和 `task_group` 字段
   - 从 schedule_config.json 按 target schema 取默认值（读 ~/.config/opencode/schedule_config.json）
   - designer 在 design_decisions 的 schedule 段可覆盖（如 `schedule.task_project_override`）
   - 缓存连接不涉及（schedule_config 是本地 json，不连库）

3. **改 `skills/dws-design/assets/ts-template.json`**：
   - tasks.f/view/dq 每个加 project_name/task_group 字段（注释说明来源）
   - upstream 项的 project/group 字段已有（之前加的），保持

4. **改 `skills/dws-design/scripts/assemble_ts.py` 的 render_md §6**：
   - 调度任务表改为显示完整路径：
     ```
     | 项目 | 任务组 | 调度任务 | 执行Job | 调度周期 |
     |------|--------|---------|---------|---------|
     | SRP_DAILY | GROUP_SPRD | task_xxx_f | Pjob_xxx_f | 0 30 3 * * ? |
     ```
   - 上游依赖表加 项目/任务组 列（从 upstream 项的 project/group 取，跨项目依赖时能看到归属）

5. **改 `skills/dws-coding/scripts/assemble_export.py`**：
   - schedule_tasks.xlsx 的 tasks/jobs/taskParams sheet：project/task_group 从 ts.json 的 tasks 里取（不再从 platform_config 的 lts 段取）
   - platform_config 的 lts 段只保留 appid（如果 lts 段还有 project_name/task_group，作为 fallback 兼容）

6. **改 `skills/dws-design/assets/design-decisions-template.yaml`**：
   - schedule 段加可选的覆盖字段（designer 填特殊任务的项目组，如初始化）：
     ```yaml
     schedule:
       schedule_type: "daily"
       cron: "0 30 3 * * ?"
       upstream_added: []
       # 以下可选：覆盖 schedule_config 的默认 project/task_group
       # task_project_override:
       #   init: { project_name: "SRP_INIT", task_group: "GROUP_INIT" }
     ```

7. **改 `install.py`**：
   - schedule_config.example.json 的拷贝逻辑（和 db-sources.example.json 一致：拷到 ~/.config/opencode/，不覆盖已有）

8. **测试更新**：
   - assemble_ts 的测试：tasks 段有 project_name/task_group
   - assemble_export 的测试：project/task_group 从 ts.json 取（不是 platform_config）
   - render_md 的测试：调度段显示完整路径

**约束**：
- schedule_config.json 是本地配置（~/.config/opencode/），不进仓库（和 db-sources/platform_config 一致）
- 兼容：ts.json 没有 project/task_group 的旧产出，export 时 fallback 到 platform_config
- 全套测试必须通过

**验证标准（四项全过才提交）**：
1. `python3 -m pytest tests/ -q` 全套通过
2. `python3 install.py` 无报错
3. 对 002 跑 assemble_ts，确认 ts.json 的 tasks.f 有 project_name/task_group
4. 对 002 跑 assemble_export，确认 schedule_tasks.xlsx 的 tasks sheet 有正确的 project/task_group
5. 四项全过 → `git add -A && git commit && git push origin main`，提交信息写明改动。任一项不过不提交，如实报告。

---

### 任务五：排查单元测试覆盖缺口并补充

**背景**：之前 `resolve_all_params` 函数被 Edit 操作撕裂（函数体截断无 return），
导致 UT 执行脚本报错。但没有测试挡住——因为这个函数没有直接单元测试，只被
UT 脚本间接调用（而测试环境连不了库，走不到间接路径）。要排查所有类似缺口。

**这是最后一个任务的原因**：前面四个任务都改了代码（preprocess/assemble_ts/
explore.py/assemble_export），本任务补测试要覆盖到这些新代码。必须最后做。

**排查方法**：

对以下脚本里的**每个公开函数（def 开头、不以 _ 开头的）**，检查是否有对应的单元测试。
重点排查"被其他脚本 import 的函数"——这些是跨模块依赖，一旦行为变了影响面大。

要排查的脚本和函数（按优先级排）：

**高优先级（跨模块 import，行为变化影响大）**：

1. `skills/dws-coding/scripts/run_ut.py`：
   - `resolve_all_params` — ✅ 已补
   - `resolve_test_value` — 有测试？检查
   - `substitute_params` — 有测试？检查
   - `wrap_insert` — 有测试？检查（test_coding_scripts.py 有 TestInsertWrapping）
   - `read_select` — 有测试？检查
   - `resolve_sample_blocks` — ✅ 已补（test_inject_tablesample.py）
   - `inject_tablesample` — ✅ 已补

2. `skills/dws-coding/scripts/check_sql.py`：
   - `check_sql` — 有测试？检查（test_coding_scripts.py 有 TestCheckSql）
   - `read_sql` / `split_cte_main` / `extract_select_aliases` / `extract_from_tables`
     / `check_bracket_balance` / `check_no_select_star` — 逐个检查

3. `skills/dws-coding/scripts/assemble_ddl.py`：
   - `generate_ddl` / `generate_create_table` / `generate_create_view`
     / `generate_rollback` / `split_table_ref` / `type_or_empty` — 逐个检查

4. `skills/dws-coding/scripts/assemble_dq.py`：
   - `generate_dq_sql` / `generate_dq_for_table` — 有测试？检查

5. `skills/dws-coding/scripts/assemble_export.py`：
   - `load_platform_config` / `resolve_config_by_schema` / `_cfg`
     / `build_rule_rows` / `build_group_variables` / `build_target_fields` — 逐个检查

6. `skills/dws-coding/scripts/slice_ts.py`：
   - `slice_rule` — 有测试？检查（test_coding_scripts.py 有 TestSliceTs）

7. `skills/design-dev-shared/scripts/dws_db.py`：
   - `resolve_password` — ✅ 有测试
   - `load_db_sources` / `resolve_source_by_schema` / `load_test_params` — 检查
   - `create_executor` / `create_executor_for_schema` — 有 roles 测试

8. `skills/dws-design/scripts/precheck.py`：
   - `precheck` — ✅ 有测试（test_precheck_db.py）
   - `_load_schema_cache` / `_save_schema_cache` / `_is_cache_expired`
     / `_fetch_tables_schema_batch` / `_normalize_type` — 逐个检查

9. `skills/dws-design/scripts/gate_summary.py`：
   - `generate_gate1_summary` — 有测试？检查（很可能没有，补上）

10. `skills/dws-design/scripts/assemble_ts.py`：
    - `assemble_ts` / `build_exec_params` / `build_tables` / `build_rule`
      / `is_dim_table` / `validate_decisions` / `render_data_flow_mermaid` — 逐个检查
    - ★ 任务二新增的 step_type 搬运逻辑也要补测试

11. `skills/dws-design/scripts/preprocess.py`：
    - `build_compact` — ✅ 有测试（任务一会补 incremental_tables 相关）
    - `extract_rs_data` / `parse_mapping` / `build_rs_input` / `slim_mapping_data` — 逐个检查
    - ★ 任务一新增的 incremental_tables 解析逻辑也要补测试

**中优先级（内部使用，但逻辑复杂）**：

12. `skills/dws-design/scripts/explore.py`（任务三新建）：
    - 参数解析 / SQL 拼接 / 输出格式 — 补测试

> 注：`sql_validator.py` / `validate_ddl.py` / `verify_files.py` 已于 2026-08 清理删除（零生产引用、零/孤儿测试），从本任务排查清单移除。`run_ut.py` / `assemble_dq.py` 的整改见任务六。

**做法**：
- 对每个函数，先 grep 测试文件确认有没有被测过
- 没测过的 → 补单元测试（不连库、不依赖外部文件，用 mock/dict 构造输入）
- 测试要覆盖：正常路径 + 边界条件 + 错误处理（如缺值 exit、异常回退）
- 每个 `pytest.raises(SystemExit)` / 返回值断言 / 行为验证都算

**约束**：
- 只补**纯逻辑函数**的测试（不连库、不读真实文件、不依赖外部环境）
- 需要连库/读 xlsx 的函数用 mock 测核心逻辑（参数解析、SQL 拼接、返回值格式）
- 不要为了凑覆盖率写无意义的测试——每个测试要验证一个明确的行为
- **覆盖前面任务一/二/三/四新增的代码**（step_type 搬运 / incremental_tables 解析 / explore.py / schedule 路径）
- 补完跑 `python3 -m pytest tests/ -q` 确认全套通过

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 汇报：补了哪些函数的测试、之前缺测的有哪些、有没有发现新的 bug

---

### 任务六：遗产脚本整改（assemble_dq / run_ut 并入现行体系）

**背景**：2026-08 清理死代码时，保留了两个"看着 legacy 实则有依赖"的脚本。它们不该长期以 legacy 状态存在——本任务把它们整进现行体系，消除遗产。

#### 子任务 A：assemble_dq.py 退役（eval-suite 对齐生产）

- **现状**：生产 new-pipe 早已改 **coder 生成 DQ**（assemble_dq 标记废弃），但 **`eval-suite/local_eval.py` 仍调 assemble_dq.py**（`step_assemble_dq`，line 244/486）。两路 DQ 产出路径不一致是长期隐患（见 idle-regression-report-20260804）。
- **整改**：让 eval-suite 改走 coder 生成 DQ（复用生产的 `dq/` 产出，或 local_eval 在编码步骤并行调 coder 产 DQ），对齐后删 `assemble_dq.py` + `tests/test_assemble_dq.py` + new-pipe.md / tool-registry.md 里的废弃说明。
- **顾虑**：回归报告记过"多一次 AI 调用可能引入不稳定"——整改时务必验证 eval 结果不退化（DQ 产出条数/内容与改前一致）。
- **验收**：grep 全仓无 `assemble_dq` 引用；eval-suite 跑通且 DQ 产出与改前一致。

#### 子任务 B：run_ut.py 去 legacy 化

- **现状**：`run_ut.py` 实为 **UT 函数库**（`wrap_insert` / `wrap_write` / `run_ut_check` / `inject_tablesample` / `substitute_params` / `resolve_all_params` 等，被 `ut_precheck.py` / `ut_execute.py` import），但文件名 + 残留的 `main()` 单执行器让它"看着 legacy"（tool-registry 之前标错过）。
- **整改（二选一，权衡可维护性）**：
  - **方案 1（轻）**：保留 `run_ut.py`，清除或显式标注 legacy `main()`，文件头注释明确"UT 函数库（ut_precheck/ut_execute import），main() 为已弃用单执行器，new-pipe 走 6a/6b"。
  - **方案 2（重）**：拆为 `ut_lib.py`（纯函数库）+ 删 `main()`，`ut_precheck` / `ut_execute` 改 import `ut_lib`。彻底消除 legacy 名义，但改动面大。
- **验收**：`ut_precheck` / `ut_execute` import 不破；全量 pytest 过；`run_ut` 不再在任何文档里被标 legacy。

**做法 / 约束**：同前——只改这些脚本 + 它们的引用点；改完跑 `python3 -m pytest tests/ -q` 全套通过；同步更新 `docs/tool-registry.md`（assemble_dq 删条目 / run_ut 去legacy标注）。

**验证**：`python3 -m pytest tests/ -q` 全套通过 + 汇报：A/B 各选了哪个方案、改了哪些文件、是否彻底消除 legacy。

---

### 收尾
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. **自动提交**：`git add -A && git commit && git push origin main`
3. 如实汇报：改了哪些文件、测试结果、遇到的问题
