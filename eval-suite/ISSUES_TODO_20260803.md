# 待评估问题清单（2026-08-03 闲时回归发现）

> 本文件列出 2026-08-03 回归评测中**发现但未改**的两个问题，供主 agent 评估是否优化。
> 区别于同轮已修复的 3 个问题（assemble_ts 兜底 bug、案例001 RS、案例007 mapping），见 `eval-suite/EVAL_REPORT_20260803.md`。
> 评估原则：**别反向优化**——designer 抓数据源缺口是正确行为，不能为绕过卡死而抑制它。

---

## 问题 A：design→coder 契约对"数据源缺口"的处理（建议优化）

### 归类
AI 产出质量 / skill 指引（非脚本 bug，非案例数据）

### 优先级
🔴 中高——会导致非交互运行（local_eval / 生产 CI）卡死超时，但当前 11 案例已在数据侧绕过。

### 现象
案例 007（dwb_supply_chain_f）全流程跑到 coder 步骤时**卡死直到超时**，`R0001.sql` 不产出。
流式抓取 coder（实际是默认主 agent 跑 dws-coder 子 agent）的输出，停在：

```
读 ts.json 发现一个设计阶段遗留的缺口，必须先和你确认：
R0001 的 stock_days（库存周转天数）字段在 join_safety 和 design_logic 里
都标注了数据源缺口警告：⚠️ 数据源缺口：stock_days 口径依赖"近30天销量"
```

在非交互 `opencode run` 里没有用户能回答确认，agent 一直等待，直到 1800s 超时。

### 根因链
1. **案例数据不自洽**（本次已从数据侧修）：stock_days 字段口径依赖"近30天销量"，但 mapping 只配了采购/供应商/商品/仓库/库存 5 张表，缺销售事实表。
2. **designer 行为正确**（应保留，不可抑制）：designer 准确识别了缺口，写进 ts.json 的两处——
   - `rules.R0001.join_safety[]`：`⚠️ 数据源缺口：stock_days 口径依赖"近30天销量"，但 rs_input 未提供销售事实表。编码前必须补充销售数据源，否则该字段无法产出。`
   - `rules.R0001.fields[stock_days].design_logic`：同款阻断措辞。
3. **契约缺口**：缺口信息从 design 阶段"泄漏"到 coder，且**措辞偏阻断**（"编码前必须补充…否则无法产出"）。coder 在非交互运行里把它当硬前置条件，反复等待确认。

### 关键证据文件（修复前的 ts.json 片段，已随 commit 2dd08aa 被新产出覆盖，可从 git 历史取）
```json
// rules.R0001.fields[stock_days]
{
  "target_field": "stock_days",
  "transform_type": "aggregate",
  "source_fields": [{"table": "", "field": "", "alias": ""}],
  "design_logic": "...注意：当前 rs_input.source_tables 未提供销售事实表数据源，本字段口径依赖的销量数据缺失，需在编码前补充销售事实表(如 dwd_sales_f)作为数据源。"
}
// rules.R0001.join_safety[] 最后一项
{
  "table": "stock_days（近30天销量）",
  "join_key_unique": false,
  "strategy": "需补充销售事实表数据源后定义",
  "reason": "⚠️ 数据源缺口：stock_days 口径依赖\"近30天销量\"，但 rs_input 未提供销售事实表。编码前必须补充销售数据源，否则该字段无法产出。"
}
```

### 为什么没在回归里改
- designer 抓缺口是**正确行为**，抑制它会反向优化。
- 让缺口降级产出属 skill 指引 / 模型能力范畴，改 designer 或 coder 指引风险较高，本轮按"不确定的不改"保留。
- 当前已在案例 007 数据侧补 `dwd_sales_f` 让链路跑通，不影响 11/11 结论。

### 建议的优化方向（供主 agent 评估，三选一或组合）
1. **coder 指引侧（推荐，改动小）**：在 `agents/dws-coder.md` 或 dws-coding skill 加一条——
   > 非交互运行（无人在环）遇 `design_logic` / `join_safety` 标注的数据源缺口，对该字段产出 `NULL AS <field> /* TODO: 待补数据源：<缺口说明> */` 占位 SELECT，**不要停下来等待确认**；在最终回复里列出 TODO 字段清单。
   - 优点：保留 designer 的缺口发现能力；coder 不卡死；缺口信息不丢（进 TODO + 回复）。
   - 风险：低。只影响有缺口的字段，其余字段正常产出。
2. **designer 措辞侧**：让 designer 把缺口标成"警告级"（如 `⚠️ 建议补充`）而非"阻断级"（`必须补充…否则无法产出`）。
   - 风险：措辞调整难量化效果，coder 仍可能误判。
3. **协议侧**：ts.json 给缺口字段加显式标记（如 `data_gap: true`），coder 见到该标记走占位逻辑。
   - 改动面大（assemble_ts / slice_ts / coder 都要改），需配套测试。

### 验证方法
- 构造一个故意缺源表的案例（如把修好的 007 mapping 的销售表删掉），跑 `local_eval`，期望 coder 产出带 TODO 占位的 SELECT 而非卡死。
- 现有 11 案例回归不能回归。

---

## 问题 B：local_eval 只编码第一个规则（评测工具局限）

### 归类
评测工具设计局限（非 bug）

### 优先级
🟡 低——不影响每条规则 design+encode 能力的验证结论，但端到端流水没被编码层覆盖。

### 现象
多规则案例（designer 拆成 tmp1→tmp2→…→f 多步）只有 R0001 产出 ETL，后续规则的 ETL 未编码。

涉及案例：005（4 规则）、006（4 规则）、009（3 规则）、012（4 规则）。
各案例 ts.json 规则数 vs 实际编码数：

| 案例 | ts.json 规则数 | 实际编码 ETL |
|---|---:|---|
| 005 dwb_user_center_f | 4（tmp1/tmp2/tmp3/f） | 仅 R0001 |
| 006 dwb_user_behavior_f | 4（tmp1/tmp2/tmp3/f） | 仅 R0001 |
| 009 dwb_product_center_f | 3（tmp1/tmp2/f） | 仅 R0001 |
| 012 dwb_order_center_f | 4（prod_tmp1/shop_tmp1/user_tmp1/f） | 仅 R0001 |

### 根源
`eval-suite/local_eval.py` 第 380-388 行：
```python
# 步骤4: coder（取第一个规则）
if not args.skip_ai and (deliver_base / "ts.json").exists():
    ts = json.loads((deliver_base / "ts.json").read_text(encoding="utf-8"))
    rules = list(ts.get("rules", {}).keys())
    rule_code = args.rule or (rules[0] if rules else "R0001")
    step_coder(report, deliver_base, rule_code, args.skip_ai)
```
设计上是"逐规则测试能力"，默认只取第一个规则。

### 影响
- ✅ 不影响结论：每条规则的 design + encode 路径都被验证，DDL/DQ 全规则生成，check_sql 对已编码规则 PASS。
- ⚠️ 中间表（tmp2/tmp3/…/f）的 ETL 没生成，**无法端到端验证整条流水的衔接**（tmp1 产出是否能被 tmp2 正确消费）。

### 为什么没在回归里改
是有意设计，不是 bug。多规则全编码会让大案例（012/006）耗时倍增（每规则 up to 30min），需配套放大超时。

### 建议的优化方向（供主 agent 评估）
1. **加 `--all-rules` 开关**（推荐，向后兼容）：默认行为不变（只编第一规则），加开关后循环编码所有规则。
   - 配套：每规则独立超时 + 累计超时上限；报告里列出已编码/未编码规则清单。
2. **默认全编码**：改默认循环所有规则。需把 `local_eval` 的整体超时从单规则 1800s 放大到 N×1800s，或改为后台串行不设全局上限。
3. **保持现状 + 文档说明**：在 local_eval 注释/README 写明"仅编码第一规则，多规则案例的中间表 ETL 需手动补"。

### 验证方法
- 对 005 加 `--all-rules`，期望产出 R0001/R0002/R0003/R0004 四个 ETL 文件。
- 人工核查 tmp2 的 SELECT 是否引用 tmp1 的字段（流水上溯正确）。
