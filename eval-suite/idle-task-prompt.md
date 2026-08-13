# 闲时任务提示词

> 用于空闲时段执行。复制下面**待办任务**的提示词给 agent，在项目目录下执行。
> 按编号顺序做（后者覆盖前者产出物）。顺序原则：**先改功能（一/二/三），后挪文件（四），回归收尾（五）**——归位之后不再改代码，避免挪了又改。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：遗产脚本整改（assemble_dq / run_ut 并入现行体系）

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

### 任务二：校验分级与容错（precheck 增强 + RS 解析容错 + 大小写）

**背景**：校验链路有几个可强化点（不阻断核心流程，属严谨性/容错性优化）：
1. **源表级 source_alias 空**（precheck.py，源表校验处）现在是 warn，建议升 error——源表没别名，字段级 source_alias 无从引用（虽字段级校验间接拦，但源头拦更清晰）
2. **error 消息缺修复指引**：现在只报问题（如"字段 X 缺少来源字段"），没说怎么改。建议加修复指引，让用户/BA 知道改哪个源文件、哪一列
3. **数据加工 source_column 空** 维持 warn（纯派生如 COUNT(*) 合法），只确认消息够清晰
4. **RS 解析不容错**：L1.1 段缺失/格式乱（RS 生成不稳定是常态）时 preprocess 直接 exit(1)——应改为**解析兼容**（mapping 目标表兜底 + warning 标记，继续产 rs_input），质量判断留给 precheck 提示
5. **目标表校验大小写敏感**：validate_target_table 比对 `rs_schema != mapping_schema` 大小写敏感，仅大小写差异（Ods.ODS_B vs ods.ods_b）误报"不一致"——比对改 lower，仅大小写差异视为一致（warning 提示规范化即可）

**先读这些理解上下文**：
- `skills/dws-design/scripts/precheck.py` 的字段/别名校验段（含 3b 交叉校验 + 别名一致性 + _check_audit_fields）
- `skills/dws-design/scripts/preprocess.py` 的 L1.1 报错路径 + validate_target_table
- 现有 error/warn 消息表述（确认哪些要加指引）

**要做的**：

1. **源表级 source_alias 空升 error**：
   - 现状：`result.add_warn(f"源表 ... 缺少别名 (source_alias)")`
   - 改：`result.add_error(...)`，消息加指引"（在 mapping.xlsx 实体级定义的表别名列填，如 t/a/b）"

2. **error 消息加修复指引**（各 add_error 处，统一指向源文件）：
   - 字段缺 source_column → "在 mapping.xlsx 的 source_column 列填源表字段名"
   - 字段 source_alias 空 / 不在实体级 → "在 mapping.xlsx 的表别名列填（须与实体级定义一致）"
   - 映射规则不合法 → "改为 直接复制/数据加工/赋值/序列 之一"
   - 目标 schema/table 缺失 → "在 RS L1.1 或 mapping 目标表补 schema.table"
   - 其他 error 类似加"怎么改"指引。**统一原则：改源文件（mapping.xlsx / RS.md），不是产物 rs_input.json**

3. **RS 解析容错（第 4 点）**：preprocess 的 L1.1 段缺失/解析失败 → 降级（mapping 目标表兜底 + warning，不 exit），precheck 阶段再提示
4. **大小写不敏感（第 5 点）**：validate_target_table 比对改 lower，仅大小写差异 → warning 提示规范化（不算不一致）

5. **测试**（tests/test_precheck_db.py / test_preprocess.py）：
   - 源表级 alias 空 → 触发 error（不是 warn）
   - 关键 error 消息含修复指引关键词（如 "mapping.xlsx"）
   - L1.1 缺失 → preprocess 不 exit，mapping 兜底产出 + warning
   - 大小写差异 → 不报"不一致"，给规范化 warning

**约束**：
- 只改 precheck.py 的校验级别（warn→error）+ 消息文案 + preprocess.py 的 L1.1 降级 + validate_target_table 大小写，不动校验逻辑结构
- 修复指引统一指向源文件（mapping.xlsx / RS.md），不指向 rs_input.json
- 数据加工 source_column 空维持 warn（纯派生合法）
- RS 容错：降级只针对"段缺失/解析失败"这类输入不稳（用 mapping/默认值兜底 + warning）；结构性错误（mapping 本身烂）仍阻断

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 汇报：哪些 warn 升了 error、哪些消息加了指引、RS 容错路径

---

### 任务三：UT 报错自动诊断（ut_diagnose + INSERT 失败钩子）

**背景**：UT 报错信息不透明——数据库只说"字符转数值转换失败"，不说哪个字段、哪步；designer/coder 不能直连库排查，拿模糊报错只能瞎猜。
**方案定论**（已讨论定）：**诊断 = 脚本自动**（报错现场连着库、上下文最全：知道哪条规则/什么报错；确定性探测无语义判断，不新建 agent——agent 是岗位，设岗位要有业务判断需求）；**分析 = designer/coder**（拿诊断材料做根因判断：源脏 / 设计缺 cast / 业务一对多）；**路由 = pipe 不变**（三类分流，材料更充分而已）。先例：run_ut_check 主键重复时 LIMIT 5 捕获重复键样例——同一模式扩展到 INSERT 报错。
**关键资产**：schema_cache 里有全部字段的源/目标类型——"这条规则哪些字段跨类型"在设计数据里已知，圈嫌疑字段不用猜。

**要做的**：

1. **新建 `skills/dws-coding/scripts/ut_diagnose.py`**（函数库 + CLI，agent 可复用）：
   - 核心 `diagnose_type_error(executor, rule, ts, cache_path)`：
     读该规则字段 + schema_cache → 用 type_compat 的 `parse_type_info`（family 大类）圈出跨类型字段（源 varchar→目标 numeric 等）→ 逐个对**源表**定向探测：`SELECT count(*) WHERE 字段 NOT SIMILAR TO 数字模式`（日期类同理）+ `LIMIT 3` 抓样例值
   - 输出："字段 X 有 128 行脏数据，样例：'N/A'、'-'、'1,000'"（designer/coder 拿到直接可判断根因）
   - CLI：`python ut_diagnose.py --ts ts.json --rule R0001`（designer/coder 回退分析时可自行复跑，服务型）
2. **ut_execute INSERT 失败钩子**：报错含 `invalid input syntax` / 类型转换类关键字 → 自动调诊断 → 结果附进 UT 报告（该规则的 FAIL detail 下加"诊断"段）；识别不了的错误诚实输出"无法自动定位，附原始报错"——**诊断是增益不是依赖**
3. **边界**：只覆盖类型转换类高价值错误（先做字符→数值、字符→日期），其他报错原样透传

**约束**：
- 探测只读源表（etl 账号），单表 count/LIMIT 不会发散
- 诊断逻辑独立成模块不塞 ut_execute 主体（钩子一行调用）；schema_cache 不存在时跳过诊断（提示"未连库无缓存"）
- run_ut_check 的样例捕获模式保持一致（风格统一）

**验证**：
1. `python3 -m pytest tests/ -q` 全套通过（ut_diagnose 用 mock executor 构造脏行测试：探测 SQL 拼接 / 样例捕获 / 跨类型圈定）
2. 汇报：诊断覆盖的报错类型、输出的诊断样例格式

---

### 任务四：脚本按调用方归位（pipe 调的 → design-dev-shared）

**背景**：脚本现在按"设计/编码"skill 分，但实际调用方有三类——designer（agent）、coder（agent）、pipe（command 编排）。**pipe 调的脚本放 designer/coder skill 下会让 agent 困惑**（"这俩脚本干啥的，我本身的工作用不到"）：
- dws-design 下的 `preprocess.py` / `precheck.py` / `gate_summary.py` —— pipe 在步骤1/3 调，designer 不用
- dws-coding 下的 `assemble_ddl.py` / `assemble_export.py` / `ut_precheck.py` / `ut_execute.py` / `check_db.py` —— pipe 在步骤4/5 调，coder 不用
- design-dev-shared 已有的 `dispatch_plan.py` / `resolve_appid.py` / `schema_query.py` 也是 pipe/designer+coder 公共的（归位方向已定，新工具直接放对了地方）

**要做的**：

1. **挪文件**：上述 pipe 调的脚本挪到 `skills/design-dev-shared/scripts/`（文件名不变）
2. **修引用**：
   - `commands/new-pipe.md`：preprocess/precheck/gate_summary/assemble_ddl/assemble_export/ut_precheck/ut_execute/check_db 的调用从 DESIGN_SCRIPTS/CODING_SCRIPTS 改 SHARED_SCRIPTS
   - 脚本间 sys.path 推算：挪到 shared 后原本"上三级找 design-dev-shared"变同级，简化；ut_precheck/ut_execute import run_ut（dws-coding 的 UT 函数库）——跨 skill import，用 sys.path 补（conftest 已把三目录都加了，脚本内确认）；或把 run_ut 一起挪 shared（作为 UT 链路函数库，执行时判断，**import 不断为准**）
   - `agents/dws-designer.md` / `dws-coder.md` permission 路径（如有引用）
   - `docs/tool-registry.md`（按调用方列，重排）
   - SKILL.md 引用：design SKILL 不再列 preprocess/precheck；coding SKILL 不再列 assemble_ddl/ut_*（designer/coder 各自的 SKILL 只列自己调的）
3. **tests/conftest.py**：sys.path 目录确认（shared 已在列表）
4. **install.py**：不用改（scan_skills 按目录整体拷）

**约束**：
- designer 调的（assemble_ts/explore/fill_type_risk_decision）留 dws-design；coder 调的（slice_ts/check_sql/**pick_fields——含 coder 专属的 --alias/--field 入口，留 coding 不拆**）留 dws-coding
- 查缓存字段的公共能力已在 shared/schema_query.py（designer/coder 共用），归位时不要重复建
- dws_db/config_paths 本来就在 shared，不动
- 挪完全链路 import 不能断

**验证**：
1. `python3 -m pytest tests/ -q` 全套通过
2. `python3 install.py --check` 组件扫描正常
3. grep 无残留旧路径引用（如 dws-design/scripts/preprocess）

---

### 任务五：排查单元测试覆盖缺口并补充

**背景**：之前 `resolve_all_params` 函数被 Edit 操作撕裂（函数体截断无 return），导致 UT 执行脚本报错。但没有测试挡住——因为这个函数没有直接单元测试，只被 UT 脚本间接调用（而测试环境连不了库，走不到间接路径）。要排查所有类似缺口。

**这是最后一个任务的原因**：前面的任务（一、二、三、四）都改了代码，本任务补测试 + 回归要覆盖到所有新代码（尤其任务一的 legacy 整改 + 任务二的校验分级与容错 + 任务三的 ut_diagnose + 任务四的脚本归位）。**必须最后做（一 → 二 → 三 → 四 → 五）**。

**排查方法**：

对以下脚本里的**每个公开函数（def 开头、不以 _ 开头的）**，检查是否有对应的单元测试。重点排查"被其他脚本 import 的函数"——这些是跨模块依赖，一旦行为变了影响面大。

要排查的脚本和函数（按优先级排）：

**高优先级（跨模块 import，行为变化影响大）**：

1. `skills/dws-coding/scripts/run_ut.py`（或归位后的所在）：
   - `resolve_all_params` — ✅ 已补（含三层兜底链）
   - `resolve_test_value` / `substitute_params` / `wrap_insert` / `wrap_write` / `read_select` / `resolve_sample_blocks` / `inject_tablesample` — 逐个检查
2. `skills/dws-coding/scripts/check_sql.py`：
   - `check_sql` / `read_sql` / `split_cte_main` / `extract_select_aliases` / `extract_from_tables` / `check_bracket_balance` / `check_no_select_star` — 逐个检查
3. `skills/dws-coding/scripts/assemble_ddl.py`：
   - `generate_ddl` / `generate_create_table` / `generate_create_view` / `generate_rollback` / `split_table_ref` / `type_or_empty` / `normalize_type` — 逐个检查
4. `skills/dws-coding/scripts/assemble_export.py`：
   - `load_platform_config` / `resolve_config_by_schema` / `_cfg` / `build_rule_rows` / `build_group_variables` / `build_target_fields` — 逐个检查
5. `skills/dws-coding/scripts/slice_ts.py`：
   - `slice_rule` — 检查（test_coding_scripts.py 有 TestSliceTs / TestSliceInit）
6. `skills/dws-coding/scripts/pick_fields.py`：
   - `gen_direct_line` / `query_table_fields` — 检查
7. `skills/design-dev-shared/scripts/dws_db.py`：
   - `resolve_password` / `load_db_sources` / `resolve_source_by_schema` / `load_test_params` / `create_executor` / `create_executor_for_schema` — 检查
8. `skills/design-dev-shared/scripts/config_paths.py`：
   - `opencode_root` / `config_dir` / `resolve_appid` — ✅ 已补
9. `skills/design-dev-shared/scripts/dispatch_plan.py`：
   - `build_dispatch_plan` — ✅ 已补
10. `skills/design-dev-shared/scripts/schema_query.py`：
    - `query_fields` — ✅ 已补
11. `skills/dws-design/scripts/precheck.py`：
    - `precheck` — ✅ 有；`_load_schema_cache` / `_save_schema_cache` / `_is_cache_expired` / `_fetch_tables_schema_batch` / `_check_type_risk` / `_apply_type_decision`（✅ 已补）— 逐个检查
12. `skills/dws-design/scripts/gate_summary.py`：
    - `generate_gate1_summary` — 检查（很可能没有，补上）
13. `skills/dws-design/scripts/assemble_ts.py`：
    - `assemble_ts` / `build_exec_params` / `_should_inject` / `_is_incremental_asset` / `build_tables` / `build_rule` / `is_dim_table` / `validate_decisions` / `render_data_flow_mermaid` — 逐个检查（build_exec_params/_should_inject 已有注入测试）
14. `skills/dws-design/scripts/preprocess.py`：
    - `build_compact` / `extract_rs_data`（容错改造后）/ `parse_mapping` / `build_rs_input` / `validate_target_table`（大小写改造后）/ `slim_mapping_data` — 逐个检查

**中优先级（内部使用，但逻辑复杂）**：

15. `skills/dws-design/scripts/explore.py`：参数解析 / SQL 拼接 / 输出格式 — 检查
16. `skills/dws-coding/scripts/ut_diagnose.py`（任务三新建）：`diagnose_type_error` — 任务三已带测试则确认覆盖

> 注：`assemble_dq.py` 已在任务一退役（若执行到本任务时已删）。`run_ut.py` / `assemble_dq.py` 的整改见任务一。

**做法**：
- 对每个函数，先 grep 测试文件确认有没有被测过
- 没测过的 → 补单元测试（不连库、不依赖外部文件，用 mock/dict 构造输入）
- 测试要覆盖：正常路径 + 边界条件 + 错误处理（如缺值 exit、异常回退）
- 每个 `pytest.raises(SystemExit)` / 返回值断言 / 行为验证都算

**约束**：
- 只补**纯逻辑函数**的测试（不连库、不读真实文件、不依赖外部环境）
- 需要连库/读 xlsx 的函数用 mock 测核心逻辑（参数解析、SQL 拼接、返回值格式）
- 不要为了凑覆盖率写无意义的测试——每个测试要验证一个明确的行为
- **覆盖任务一（legacy 整改）+ 任务二（校验分级与容错）+ 任务三（ut_diagnose）+ 任务四（脚本归位）的新代码**
- 补完跑 `python3 -m pytest tests/ -q` 确认全套通过

**验证**：
- `python3 -m pytest tests/ -q` 全套通过
- 汇报：补了哪些函数的测试、之前缺测的有哪些、有没有发现新的 bug

---

### 收尾
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. **自动提交**：`git add -A && git commit && git push origin main`
3. 如实汇报：改了哪些文件、测试结果、遇到的问题
