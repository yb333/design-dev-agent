# 闲时任务提示词：skill 目录规范化 + 能力陷阱用例构造

> 用于空闲时段执行。复制下面的提示词给 agent，在项目目录下执行。
> 两件事独立，任务一（目录规范化）是基础设施改动，建议先做。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：skill 目录规范化（脚本进 scripts/，模板资源进 assets/）

**背景**：现在 skill 的脚本（.py）和模板资源（.yaml/.json/.md）都混在 references/ 下，要按职责拆分。

**目标目录结构**（scripts/ 和 assets/ 都与 references/ 同级，即在 skill 根目录下）：
```
skills/dws-design/
├── SKILL.md
├── scripts/          ← 所有 .py 脚本
│   ├── assemble_ts.py
│   ├── gate_summary.py
│   ├── precheck.py
│   └── preprocess.py
├── assets/           ← 模板、规范、示例等资源
│   ├── design-decisions-template.yaml
│   ├── design-guide.md
│   ├── rs-input-format.md
│   ├── ts-template.json
│   └── ts-template.md
└── references/       ← 迁移后应为空（或删除）
```

**要迁移的文件清单**（三个 skill）：

`skills/dws-design/`：
- → scripts/：assemble_ts.py, gate_summary.py, precheck.py, preprocess.py
- → assets/：design-decisions-template.yaml, design-guide.md, rs-input-format.md, ts-template.json, ts-template.md

`skills/dws-coding/`：
- → scripts/：assemble_ddl.py, assemble_dq.py, assemble_export.py, check_db.py, check_sql.py, run_ut.py, slice_ts.py, sql_validator.py, ut_execute.py, ut_precheck.py, validate_ddl.py, verify_files.py
- → scripts/lib/（保留子目录）：lib/dws_preprocessor.py
- → assets/：db-sources.example.json, dws-coding-standards.md, etl-templates.md, platform_config.example.json

`skills/design-dev-shared/`：
- → scripts/：dws_db.py
- → assets/：（无）

**迁移后必须检查并修正的引用点（6 类，逐个核对）**：

1. **SKILL.md 里的路径引用**（两个 skill 的 SKILL.md 都要改）：
   - `skills/dws-design/SKILL.md`：所有 `references/xxx.yaml`、`references/xxx.md`、`references/xxx.json` → 按文件类型改 `assets/xxx`（模板资源）或 `scripts/xxx.py`（脚本）。注意第15行"location 的同级目录就是 references/"这句话要改成说明 scripts/ 和 assets/ 的结构。第51行 `{skill目录}/references/slice_ts.py` 改 `{skill目录}/scripts/slice_ts.py`。
   - `skills/dws-coding/SKILL.md`：同理，etl-templates.md/dws-coding-standards.md → assets/；slice_ts.py 等 → scripts/。第138行"工具脚本在同目录 references/ 下"改为"在 scripts/ 下"。

2. **commands/new-pipe.md**：
   - DESIGN_SCRIPTS / CODING_SCRIPTS 变量定义（第49行）原指 references/，现在指 scripts/。确认变量获取逻辑改成定位 scripts/ 目录。
   - 所有 `CODING_SCRIPTS/xxx.py`、`DESIGN_SCRIPTS/xxx.py` 调用不变（变量名没变，指向变了）。

3. **脚本之间的 import（sys.path 推算）**——这是最容易出错的地方：
   - coding 脚本引用 design-dev-shared：现在是 `Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "references"`。迁移后脚本从 references/ 进 scripts/，`parent` 层级不变（都在 skill 目录下一级），但目标要从 `"design-dev-shared" / "references"` 改成 `"design-dev-shared" / "scripts"`。涉及的文件：check_db.py、ut_precheck.py、ut_execute.py、run_ut.py（搜 `design-dev-shared` 确认）。
   - design 的 precheck.py 同理（搜 `design-dev-shared` / `references` → 改 `scripts`）。
   - 同目录 import（`from run_ut import`、`from dws_db import`）：都在 scripts/ 下，仍同目录，`sys.path.insert(0, Path(__file__).parent)` 仍成立，不用改。
   - sql_validator.py 引用 `lib/dws_preprocessor.py`：`Path(__file__).parent / "dws_preprocessor.py"` → 改 `Path(__file__).parent / "lib" / "dws_preprocessor.py"`（lib 子目录保留）。

4. **install.py**：
   - 第274行 `skills/dws-coding/references/db-sources.example.json` → `skills/dws-coding/assets/db-sources.example.json`
   - 第290行 `skills/dws-coding/references/platform_config.example.json` → `skills/dws-coding/assets/platform_config.example.json`
   - copy_dir 是整个 skill 目录拷贝，scripts/ assets/ 子目录会跟着拷，不用改 copy_dir 逻辑。
   - 确认 install 后 `~/.config/opencode/skills/{skill}/scripts/` 和 `assets/` 都存在。

5. **tests/conftest.py**：
   - DESIGN_REFS / CODING_REFS / DD_SHARED_REFS 指向 `references/`，现在脚本进 scripts/，改成 `... / "scripts"`。

6. **eval-suite/v2/ 的脚本路径引用**：
   - `eval-suite/v2/pipeline.py` 的 DESIGN_REFS / CODING_REFS（指向 `~/.config/opencode/skills/dws-{design,coding}/references`）→ 改 `/scripts`。
   - `eval-suite/v2/assert_sql.py` 和 engine.py 里 `validators` 的 import 路径不变（那是 eval-suite 自己的，不是 skill）。

**约束**：
- 用 `git mv` 移动文件（保留 git 历史）。
- references/ 迁移完如果空了就删掉（含 __pycache__）。
- 每改完一类引用点，跑一次 `python3 -m pytest tests/ -q` 确认不破坏（现在 226 个测试）。
- 全部改完后，重跑 `python3 install.py`，确认 install 后目录结构正确，再跑一次测试。

**验证标准**：
1. `python3 -m pytest tests/ -q` 全套通过
2. `python3 install.py` 无报错，`~/.config/opencode/skills/dws-coding/scripts/slice_ts.py` 存在
3. `python3 ~/.config/opencode/skills/dws-coding/scripts/check_db.py` 能跑（验证 import 链）
4. 对 002 跑 `python3 eval-suite/v2/run.py --case 002 --skip-ai` 不崩
5. 如实报告：移了哪些文件、改了哪些引用、测试结果、有没有遗漏

---

### 任务二：能力陷阱用例构造（设计 + 实现 3 个陷阱用例）

现有用例（001-012）都是正常输入，只能测稳定性。要造"能力陷阱用例"——测 agent "该想到的想到了吗"，不是测"能不能跑通"。

**方法论**（每个陷阱 = 埋雷输入 + 正确行为契约 + 断言）：
- 埋雷输入：mapping/RS 里故意留会诱导犯错的细节
- 正确行为契约：agent 应该识别什么、产出什么
- 断言：checks.yaml 配"必须有的决策"（must_actions）和"禁止出现的错误"（must_not）
- 每个陷阱配一个"干净对照版"（同样结构不埋雷），防 agent 过度警觉误报

---

### 先造这 3 个陷阱（按价值排，构造从易到难）

#### 陷阱 T1：头行整合主键发散（business_key 判断）
- **埋雷**：mapping 目标表是头行整合宽表（字段来自 ods_order 头表 + ods_order_line 行表），但 mapping 主键标注只写了头表主键 `order_id`。RS 写"一行=一个订单的一个商品行"。
- **契约**：designer 应识别粒度是订单行级，business_key 扩展为 `[order_id, line_id]`，标注"原主键会发散已扩展"。
- **断言**：
  - ✅ must: `business_key == [order_id, line_id]`（design 层）
  - ❌ must_not: `business_key == [order_id]`
- **干净对照版**：同样的表结构，但 mapping 主键正确标了 `[order_id, line_id]`，断言 `business_key == [order_id, line_id]`。

#### 陷阱 T2：RS 标增量但配全量（增量识别）
- **埋雷**：RS 正文角落写"本表每日增量更新，基于 update_time 取昨日新增"，但 mapping 看起来像全量（主键稳定、字段简单），没有任何 incremental 列提示。
- **契约**：designer 应主动扫 RS 识别增量，产出至少一条规则 load_mode != truncate_table + incremental 段。
- **断言**：
  - ✅ must: 至少一条规则 `load_mode in [merge_into, no_delete, delete]`（design 层）
  - ❌ must_not: 所有规则 `load_mode == truncate_table`
- **干净对照版**：RS 写"全量调度"，断言所有规则 `load_mode == truncate_table`。

#### 陷阱 T3：数据源缺口（拒绝沉默假设）
- **埋雷**：字段 customer_level 口径依赖 `dwd_customer_rfm` 表，但 mapping 可用数据源里没这张表。给一张名字相近的 `dim_customer`（有 level_cd 字段）诱使用错来源。
- **契约**：designer 应发现缺口并标注，不默默用 dim_customer.level_cd 替代。
- **断言**：
  - ✅ must: design_decisions 里有缺口标注（design_intent 或 join_safety 含 "缺口"/"缺失"/"dwd_customer_rfm"）
  - ❌ must_not: field_logics 把 customer_level 映射到 dim_customer
- **注意**：这个断言现在 assert_design 不直接支持（"字段不能映射到某表"），可能要给 assert_design 加一个 `field_not_mapped_from` 断言类型。如果加，按现有断言模式扩展，加测试。

---

### 每个陷阱要产出
1. `eval-suite/cases/T{N}_{名}/{mapping.xlsx, RS.md}` —— 埋雷输入
2. `eval-suite/cases/T{N}_{名}_clean/{mapping.xlsx, RS.md}` —— 干净对照
3. `eval-suite/cases/T{N}_{名}/checks.yaml` —— 断言（must/must_not）
4. `eval-suite/cases/T{N}_{名}_clean/checks.yaml` —— 对照断言
5. 用 `--skip-ai` 跑一遍确认结构 OK（这些陷阱要 designer 真跑才有意义，skip-ai 只验脚本链路+断言引擎不崩）

### 约束
- 陷阱用例编号用 T 前缀（T1/T2/T3），和 001-012 区分
- mapping.xlsx 要真实可被 preprocess 解析（参考 002 的 mapping 结构）
- 陷阱的 checks.yaml 必须能被现有 engine 跑通（assert_artifacts/assert_design/assert_sql）
- 如果发现 assert_design 缺某个断言类型（如 T3 的 field_not_mapped_from），扩展它并加测试
- 每一步如实报告：构造了什么、跑了什么、有没有报错

### 验证
对每个陷阱用例跑 `python eval-suite/v2/run.py --case T1 --skip-ai --cases-dir eval-suite/cases/`，确认断言引擎不崩、报告正常输出。如实报告结果。

---

### 收尾
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. 如实汇报：加了哪些陷阱用例、测试结果、遇到的问题
3. 不要 git commit（等我 review）
