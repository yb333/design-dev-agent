# 闲时任务提示词：能力陷阱用例构造

> 用于空闲时段执行。复制下面的提示词给 agent，在项目目录下执行。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/docs/eval-v2-design.md` 和 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 CLAUDE.md 第155行的 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

任务是构造"能力陷阱用例"——测 agent "该想到的想到了吗"，不是测"能不能跑通"。现有用例（001-012）都是正常输入，只能测稳定性。

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
