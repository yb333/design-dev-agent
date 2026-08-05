# 评测体系 v2 设计方案

> 状态：已认可，待执行（2026-08-02 18:00 后启动 P1）。
> 本方案新建 `eval-suite/v2/`，旧 `runner.py`/`validators/` 保留不动。

---

## 一、为什么重做（现状诊断）

仓库现有两套并行评测，各自只解决一半问题：

- **`local_eval.py`**：全链路冒烟 + 格式守卫（PASS/FAIL/WARN）。本质是回归测试。缺：标准答案对比、评分、对照组、分阶段计时、角色归因。
- **`runner.py` + validators + golden**：分层评分框架思路对，但**与新流水线严重脱节**——期望 `02_design/design.md`+`05_etl/`，实际产出是 `ts.json`+`ddl/`+`select/`；design validator 用正则解析已弃用的 design.md；只有一个 golden 案例（旧格式）。基本跑不起来。

业务诉求：标准用例（输入+期望输出）→ 跑 → 对比评分 → 指出问题 → 归因到角色/流程 → 分阶段耗时；搬内网用真实案例跑；支持从跑通结果自动生成断言。

## 二、设计原则（业界共识）

调研 HumanEval/MBPP/SWE-bench（代码）、WebArena/τ-bench（agent）、dbt test/Great Expectations/Datafold（ETL）后：
> **测行为不测实现。** 用"必须满足的检查项清单（断言）"，不依赖单份人工标准 SQL 做整体对比。

落地：判终态不判过程；断言为主、Data Diff 为辅；多解产出用集合/范围断言；LLM-judge 只做软分（Snowflake 实测 SQL 场景不够可靠，不当主裁判）。不用完整 golden 对比的理由：designer/coder 产出"一题多解"，整体对比会把合理写法判错。

## 三、四层评测模型

```
cases/{case}/{mapping.xlsx, RS.md, checks.yaml}
  → 跑流水线(分阶段打点) → 实际产出
  → 逐断言检查 → 四层评分
  → 报告(分数+归因+耗时+对比上轮)
  → 存档 results/{case}/{timestamp}/result.json
```

**层1 流程层（新增）**：每阶段退出码+耗时+失败定位（preprocess/precheck/designer/coder/assemble_ddl/assemble_dq/check_sql/ut/export）。复用 local_eval 的 step_* 划分，每步包计时器。

**层2 产物层（迁移自 local_eval 结构校验）**：ts.json 顶层键齐全、business_key 非空、audit_fields 正好4个、每规则有 load_mode、文件齐全（**确定性文件名拼接，不用 glob**）、DDL/回退成对、I视图无 SELECT *、export manifest codes_filled=false。归因→脚本。

**层3 质量层（核心）**，分两子层各判一角色，都用断言清单：
- **3a design 质量（判 designer）**：business_key 严格相等；field_targets 覆盖 rs_input 且不跨规则重复；load_mode 枚举合法；incremental 条件性存在（load_mode≠truncate_table 时必须有 key/filter/init_mode）；join_key_unique=false 时 strategy 非空；segmentation 自洽；源表集合包含；data_flow 无环。对错问题用严格相等，创造性产出用范围。
- **3b code 质量（判 coder）**：基于 SQL AST 语义检查（不比字符串）。字段完整率（集合包含）；JOIN 表覆盖（集合相等，复用 `_extract_join_tables`）；del_flag 过滤（复用 `_extract_del_flag_filters`）；CASE WHEN 有 ELSE（复用 `_extract_case_whens`）；GROUP BY 粒度（复用 `_extract_groupby_columns`）；审计字段齐全；增量规则 WHERE 含 incremental.filter（**新增 WHERE 谓词提取**）；rpt_code 覆盖；无 SELECT *。

**层4 归因层（新增）**：失败项 → owner 映射（design 层→designer，code 层→coder，artifacts→脚本，pipeline→按阶段定位脚本/契约/案例数据）。

## 四、断言清单规范（checks.yaml）

替代旧 expectations.json。每条断言自带 layer+owner。涵盖：artifacts（结构契约）、design（business_key/field_targets/load_mode/incremental 条件/source_tables/join_safety/segmentation/data_flow）、code（按规则的 fields_required/join_tables/where_must_contain/group_by/case_else）、data_diff（可选，需样例数据）、style（可选，LLM judge 软分）。

断言类型语义：严格相等 / 集合相等 / 集合包含 / 存在性 / 条件非空(when X then Y) / 范围 / 禁止 / 拓扑(无环)。

## 五、Golden Seeding（自动生成断言，降低 baseline 成本）

从一次跑通结果抽取事实 → 渲染成 checks.yaml 草稿（标 [AUTO-SEEDED]）→ 人工 review → 确认后固化。
- 可自动 seed（事实明确）：field_targets 覆盖（来自 rs_input）、JOIN 表集合、GROUP BY 粒度、del_flag 过滤情况、business_key 当前值。
- 不能自动 seed（需人判断）：是否该增量、分段数是否最优、distribution_key 是否最优、join_safety 策略。
- 风险对策：seed 强制 --review 模式；未确认断言评测时只 WARN 不 FAIL（baseline: unconfirmed）。

## 六、报告设计

单用例报告含：流程层（各阶段✅/耗时）、产物层（结构检查）、design 质量（designer）、code 质量（coder，失败项标 `← coder`）、归因段（失败→角色）、与上轮对比（回退项/新问题/进步项）、总分（上轮对比）。
评分模型：总分=流程层10+产物层20+design质量35+code质量35，软分(style)不计入总分单独 bonus；权重可配。

## 七、Baseline 存档与对比

每次评测存 `results/{case}/{timestamp}/result.json`（含 git_sha、各层分数、分阶段耗时、每断言详细结果）。下次自动找最新一份做 baseline，逐项对比 PASS→FAIL(回退)/FAIL→PASS(修复)/新增FAIL(新问题)。

## 八、目录结构与执行入口

```
eval-suite/v2/
├── engine.py            断言引擎（读 checks.yaml→逐条执行→CheckResult）
├── pipeline.py          跑流水线（封装 local_eval step_*，加计时器）
├── checks_schema.py     checks.yaml 解析校验
├── seed.py              golden seeding
├── baseline.py          存档+对比
├── report_v2.py         新报告（分层+归因+对比）
├── assert_sql.py        SQL断言（复用 content.py _extract_* + 新增 WHERE 提取）
├── assert_design.py     design断言（读 design_decisions.yaml + ts.json）
├── assert_artifacts.py  产物断言（确定性文件名，无 glob）
└── run.py               CLI入口
eval-suite/cases/*/checks.yaml    每用例断言（seed 渐进生成）
eval-suite/results/{case}/{ts}/   baseline存档（gitignore）
（旧 runner.py/validators/golden/local_eval.py 保留不动）
```
CLI：`run.py --case 002`（全流程）/`--eval-only`/`--all`；`seed.py --case 002 --review`；`run.py --compare-baseline`。
内网迁移：调起 agent 用 `opencode run --agent` CLI（无 sidecar 依赖，local_eval 已验证）；执行目录约定项目根；产出目录 `10_project_deliver/{case}/ddlc_design_dev/`；skill 路径 `~/.config/opencode/skills/...`（install 已统一）；评测引擎本身纯 python+sqlglot+openpyxl+pyyaml，内网装好依赖放好 cases 跑 run.py 即可。

## 九、复用与新建

复用：`validators/base.py`(CheckStatus/CheckResult/BaseValidator)、`validators/content.py`(6个_extract_* SQL函数)、`validators/sql.py`(parse_ddl/parse_etl/_strip_*/_clean_name/_normalize_type)、`validators/export.py`(Excel sheet检查)、`local_eval.py`(step_* 划分+调起 opencode 的 prompt 模板)、`report.py`(分层渲染思路)。
新建：v2/ 下 10 个文件 + cases/*/checks.yaml（seed 渐进）。
不碰：旧 runner.py/validators/golden/local_eval.py/check_case.py 全保留；tests/ 现有 165 测试不受影响。

## 十、落地节奏（每阶段独立验证独立提交）

- P1 骨架：engine+pipeline+assert_artifacts+report_v2+run.py（只跑流程层+产物层）→ 对 002 跑通
- P2 design/code 断言：assert_design+assert_sql(含 WHERE 提取)+checks.yaml schema → 对 002 写 checks.yaml 跑出分层评分
- P3 baseline+seeding：baseline.py+seed.py → seed 002 生成草稿 review 固化，跑两次验证对比
- P4 扩用例：003/004/005 等 seed+review → 多用例验证普适性
- P5 内网打包：文档化依赖+启动方式 → 内网一键跑

## 已确认决策
1. Golden 形态：断言清单为主（不用单份完整标准 SQL 对比）
2. 分层策略：design/code 两层都用断言清单
3. 对照组：存档+对比上轮
4. 内网：从一开始按内网优先设计（脚本自包含，约定执行目录+启动格式）
5. 旧代码：复用可用的，重写脱节的
6. 交付形态：新建 v2，旧保留
7. 内网断言来源：你补充；支持从跑通结果自动 seed 断言草稿，人工 review 固化
