# 闲时任务提示词：designer 试算 SQL + 调度任务路径进 ts.json

> 用于空闲时段执行。复制下面的提示词给 agent，在项目目录下执行。
> 两件事独立，任务一较小可先做，任务二涉及面较大。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：designer 试算 SQL（JOIN 键唯一性检查）

**背景**：designer 做 join_safety 分析时，不确定 JOIN 键在右表唯一不唯一——这是"关联会不会发散"的事实依据。RS 只给了关联方式（文字），没给键唯一性（数据事实）。需要给 designer 一个试算手段。

**注意**：只做 JOIN 键唯一性这一个场景。其他数据探索信息（表行数、空值率）RS L01 已提供，不重复。

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

### 任务二：调度任务路径（project/task_group）进 ts.json

**背景**：ts.json 的 schedule.tasks 每个 task 只有 task_name（如 task_xxx_f），没有 project/task_group。
但实际调度中，不同任务（F表/view/dq）和不同阶段（日常/初始化）可能归属不同的项目/任务组。
现在 export 时才从 platform_config 按 schema 取一个固定值，无法表达"初始化和日常不同项目组"。
要把 project/task_group 提前到设计阶段确定，进 ts.json 的每个任务。

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

### 收尾
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. **自动提交**：`git add -A && git commit && git push origin main`
3. 如实汇报：改了哪些文件、测试结果、遇到的问题
