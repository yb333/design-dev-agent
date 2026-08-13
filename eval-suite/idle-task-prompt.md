# 闲时任务提示词

> 用于空闲时段执行。复制下面**待办任务**的提示词给 agent，在项目目录下执行。
> 三个任务**有顺序依赖，按编号顺序做**（后者覆盖前者产出物）：
> 任务一（command 脚本定位改 skill 注入）→ 任务二（legacy 整改）→ 任务三（测试补缺 + 回归，最后做）

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：command 脚本定位改用 skill 注入 + config_paths 用 `__file__` 推算

**背景**：command（new-pipe.md）定位脚本目录时硬编码 `Path.home()/.config/opencode/skills/...`，假设"单一全局安装"。但 skill 可被项目级安装（`<proj>/.opencode/skills/`）或复用进别的工程，硬编码落空 → 所有脚本调用失败。同样，`config_paths.py` 的 config 定位也锚定 `Path.home()`，项目级安装时 config 也找不到。还有个附带 bug：`install.py --local` 模式下 skill 装项目级、config 却仍装全局（line 277 `rules_dir` 不分 mode），天然分裂。

**历史**（git 考古结论，避免重蹈覆辙）：
- `39d2003`（7/31）曾用 `opencode debug skill` CLI 探测 skill location（准），内网命令被阉割
- `3f9cbe2`（7/31）改用"opencode 注入的 location"，但只有加载了 skill 的 agent 才有注入
- `1928a5d`（8/3）因 command 执行者（`agent: build`，不加载 skill）拿不到注入，退化成 `Path.home()` 硬编码，沿用至今

**根因 + 解法**：opencode 给"加载了 skill 的 agent"注入 location（SKILL.md 绝对路径），但 command 的执行者 build agent 不加载 skill，拿不到注入。解法是给 `design-dev-shared`（公共代码库，现在无 SKILL.md）加一个极简 SKILL.md，让 build agent 在 command 开始时**显式调 Skill tool 加载它**，拿到 location 注入——一个 location 推出所有 scripts 目录。这是 opencode 官方标准用法（skill on-demand 加载 + location 注入，见 https://opencode.ai/v2/docs/skills ）。已实测：`opencode debug agent build` 显示 build agent 有 `"skill": true`，能调 Skill tool。

**先读这些理解上下文**：
- `commands/new-pipe.md` 的"脚本路径定位"段（line ~47，现在的 `Path.home()` python 探测 + 那句不可靠的"建议 fallback"）
- `skills/design-dev-shared/`（现状：只有 `scripts/`，无 SKILL.md）
- `skills/design-dev-shared/scripts/config_paths.py`（config 定位，现在用 `Path.home()`，本轮改用 `__file__` 推算）
- `install.py`：`scan_skills`（line 42，扫到 SKILL.md 的目录才算 skill）+ design-dev-shared 单独拷贝逻辑（line 249-254，因为现在没 SKILL.md 扫不到才单独拷）+ `--local` 模式 config 落点 bug（line 277 固定全局，不跟 mode 走）
- 现有两个 skill 的 SKILL.md frontmatter（`skills/dws-design/SKILL.md`、`skills/dws-coding/SKILL.md`）——照格式写 design-dev-shared 的

**要做的**：

1. **新建 `skills/design-dev-shared/SKILL.md`**（极简，不带工作指导，只做路径锚定）：
   ```yaml
   ---
   name: design-dev-shared
   description: >-
     设计开发公共代码库（dws_db/config_paths/resolve_appid 等共享脚本）。
     被 new-pipe command 在流程开始时加载，提供脚本目录定位锚点（location 注入）。
     不含工作指导，仅用于路径锚定 + 公共脚本暴露。
   slash: false
   ---

   # 设计开发公共库

   本 skill 是设计开发 agent 的公共代码库，**不是工作指导**，body 极简。

   ## 用途：路径锚定

   被 new-pipe command 在流程开始时加载，用于定位所有脚本目录。加载后 opencode 注入的 `location`（本 SKILL.md 绝对路径）= `.../skills/design-dev-shared/SKILL.md`，由此推算：

   - **SHARED_SCRIPTS** = location 同级 `/scripts`（即 design-dev-shared/scripts）
   - **DESIGN_SCRIPTS** = location 上三级 `/dws-design/scripts`（上三级 = skills 目录）
   - **CODING_SCRIPTS** = location 上三级 `/dws-coding/scripts`

   ## 公共脚本（SHARED_SCRIPTS 下）

   - `dws_db.py`：连库能力（DBExecutor 抽象 + PsycopgExecutor）
   - `config_paths.py`：config 文件路径解析（opencode_root 多候选探测）
   - `resolve_appid.py`：按 schema 反查 appid（CLI）
   ```
   > `slash: false` 让它不进斜杠命令列表（不是给人用的命令，只被 command 内部加载）。

2. **改 `commands/new-pipe.md` 的"脚本路径定位"段**：
   - 删掉现在的 `python -c "from pathlib import Path; p=Path.home()/..."` 探测和那句"如果全局目录不存在...用当前项目下"的不可靠 fallback
   - 改为指示 build agent：「**开始前调 Skill tool 加载 `design-dev-shared` skill**，从注入的 location 推算三个 scripts 目录」，给出推算公式（同 SKILL.md body）
   - 保留兜底（万一 skill 加载失败的极端情况）：`opencode debug skill` CLI 查 location；再退到多候选路径检查（全局 `~/.config/opencode/` / cwd 向上找 `.opencode/` / cwd 向上找 `skills/`）。兜底写成一段 python，print 第一个命中路径。

3. **改 `skills/design-dev-shared/scripts/config_paths.py`**：
   - 新增 `opencode_root()` 函数，多候选探测 opencode 根（优先级）：
     1. 环境变量 `DWS_RULES_DIR`（部署/CI/测试强制覆盖）
     2. `__file__` 推算：config_paths.py 在 `design-dev-shared/scripts/`，`parents[3]` = opencode 根；若该根下有 `_references/rules/dws-design-dev/` → 命中（config 自动跟随 skill，用户级/项目级都自动对）
     3. fallback 全局：`Path.home()/.config/opencode`（向后兼容老安装）
     4. fallback 项目级：cwd 向上找 `.opencode`（项目级安装）
     5. 全 miss：回全局路径（友好报错，不比现在差）
   - `config_dir()` 改为 `opencode_root() / "_references" / "rules" / RULES_DIR_NAME`
   - 必须幂等（assemble_ts main 的校验阶段也调，不能依赖校验通过——用防御性 `.get` + 默认值，不抛异常）

4. **改 `install.py`**：
   - design-dev-shared 有了 SKILL.md，`scan_skills`（line 42）能扫到 → **删掉 line 249-254 的单独拷贝逻辑**（那段注释"无 SKILL.md，scan_skills 扫不到，单独拷"已过时）
   - 修 `--local` 模式 config 落点 bug：line 277 的 `rules_dir = rules_config_dir()` 改为跟 mode 走（global → `~/.config/opencode/_references/rules/...`；local → `<cwd>/.opencode/_references/rules/...`），不再固定全局。这样 `--local` 模式 skill 和 config 装同根（项目级 .opencode），不再分裂。

5. **测试**（tests/）：
   - `conftest.py` 顶部设 `DWS_RULES_DIR` 环境变量指向 tmp 目录，隔离测试（不碰机器全局 config，测试不污染真实环境）
   - `test_pure_funcs.py` 加 `TestOpencodeRoot`：
     - `__file__` 推算命中（构造 config_paths.py 真实位置，验证 parents[3] 推算）
     - 环境变量覆盖优先级
     - fallback 全局（mock 不存在场景）
     - 项目级 `.opencode` 探测（构造 tmp 项目结构）
   - 全套 pytest 通过

**约束**：
- design-dev-shared/SKILL.md **极简**（只声明身份 + 路径推算说明），不放任何工作指导——避免污染加载它的 agent 上下文（它只该被 new-pipe 加载用于定位，不该给 agent 灌输方法论）
- `slash: false`（不进斜杠命令列表）
- config_paths 的 `__file__` 推算幂等（同 build_init_section 的幂等约束）
- 向后兼容：老的 `Path.home()` 全局安装仍工作（作为 fallback）
- **不动 designer/coder 的 skill**（它们已有 location 注入，不受本任务影响）
- 全程不连库、不依赖外部环境（纯路径推算逻辑）

**验证**：
1. `python3 -m pytest tests/ -q` 全套通过
2. 加载 design-dev-shared skill 能拿到 location，按公式推算出三个 scripts 目录（手动模拟或写个一次性脚本验证）
3. 模拟项目级安装场景（tmp 目录建 `.opencode/skills/design-dev-shared/scripts/` 结构）→ `opencode_root()` 的 `__file__` 推算或 fallback 命中
4. `python3 install.py --check`（在临时项目目录）无报错，scan_skills 能扫到 design-dev-shared
5. 四项全过 → `git add -A && git commit && git push origin main`，提交信息写明改动；任一不过不提交，如实报告

---

### 任务二：遗产脚本整改（assemble_dq / run_ut 并入现行体系）

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

### 任务三：排查单元测试覆盖缺口并补充

**背景**：之前 `resolve_all_params` 函数被 Edit 操作撕裂（函数体截断无 return），导致 UT 执行脚本报错。但没有测试挡住——因为这个函数没有直接单元测试，只被 UT 脚本间接调用（而测试环境连不了库，走不到间接路径）。要排查所有类似缺口。

**这是最后一个任务的原因**：前面的任务（一、二）都改了代码，本任务补测试 + 回归要覆盖到所有新代码（尤其任务一的 config_paths `__file__` 推算 + 任务二的 legacy 整改）。**必须最后做（一 → 二 → 三）**。

**排查方法**：

对以下脚本里的**每个公开函数（def 开头、不以 _ 开头的）**，检查是否有对应的单元测试。重点排查"被其他脚本 import 的函数"——这些是跨模块依赖，一旦行为变了影响面大。

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
   - `generate_dq_sql` / `generate_dq_for_table` — 有测试？检查（★ 注意任务二可能已退役本脚本，退役后本条跳过）

5. `skills/dws-coding/scripts/assemble_export.py`：
   - `load_platform_config` / `resolve_config_by_schema` / `_cfg`
     / `build_rule_rows` / `build_group_variables` / `build_target_fields` — 逐个检查

6. `skills/dws-coding/scripts/slice_ts.py`：
   - `slice_rule` — 有测试？检查（test_coding_scripts.py 有 TestSliceTs）

7. `skills/design-dev-shared/scripts/dws_db.py`：
   - `resolve_password` — ✅ 有测试
   - `load_db_sources` / `resolve_source_by_schema` / `load_test_params` — 检查
   - `create_executor` / `create_executor_for_schema` — 有 roles 测试

8. `skills/design-dev-shared/scripts/config_paths.py`（任务一新增 opencode_root）：
   - `opencode_root` / `config_dir` / `resolve_appid` — ★ 任务一新增，必须补测试（`__file__` 推算 / 环境变量覆盖 / fallback）

9. `skills/dws-design/scripts/precheck.py`：
   - `precheck` — ✅ 有测试（test_precheck_db.py）
   - `_load_schema_cache` / `_save_schema_cache` / `_is_cache_expired`
     / `_fetch_tables_schema_batch` / `_normalize_type` — 逐个检查

10. `skills/dws-design/scripts/gate_summary.py`：
    - `generate_gate1_summary` — 有测试？检查（很可能没有，补上）

11. `skills/dws-design/scripts/assemble_ts.py`：
    - `assemble_ts` / `build_exec_params` / `build_tables` / `build_rule`
      / `is_dim_table` / `validate_decisions` / `render_data_flow_mermaid` — 逐个检查
    - ★ assemble_ts 的 step_type 搬运逻辑要确保有测试覆盖（已落地功能）

12. `skills/dws-design/scripts/preprocess.py`：
    - `build_compact` — ✅ 有测试（含 incremental_tables 相关）
    - `extract_rs_data` / `parse_mapping` / `build_rs_input` / `slim_mapping_data` — 逐个检查
    - ★ preprocess 的 incremental_tables 解析逻辑要补测试

**中优先级（内部使用，但逻辑复杂）**：

13. `skills/dws-design/scripts/explore.py`：
    - 参数解析 / SQL 拼接 / 输出格式 — 补测试

> 注：`sql_validator.py` / `validate_ddl.py` / `verify_files.py` 已于 2026-08 清理删除（零生产引用、零/孤儿测试），从本任务排查清单移除。`run_ut.py` / `assemble_dq.py` 的整改见任务二。

**做法**：
- 对每个函数，先 grep 测试文件确认有没有被测过
- 没测过的 → 补单元测试（不连库、不依赖外部文件，用 mock/dict 构造输入）
- 测试要覆盖：正常路径 + 边界条件 + 错误处理（如缺值 exit、异常回退）
- 每个 `pytest.raises(SystemExit)` / 返回值断言 / 行为验证都算

**约束**：
- 只补**纯逻辑函数**的测试（不连库、不读真实文件、不依赖外部环境）
- 需要连库/读 xlsx 的函数用 mock 测核心逻辑（参数解析、SQL 拼接、返回值格式）
- 不要为了凑覆盖率写无意义的测试——每个测试要验证一个明确的行为
- **覆盖任务一（config_paths `__file__` 推算）+ 任务二（legacy 整改）的新代码**
- 补完跑 `python3 -m pytest tests/ -q` 确认全套通过

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 汇报：补了哪些函数的测试、之前缺测的有哪些、有没有发现新的 bug

---

### 收尾
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. **自动提交**：`git add -A && git commit && git push origin main`
3. 如实汇报：改了哪些文件、测试结果、遇到的问题
