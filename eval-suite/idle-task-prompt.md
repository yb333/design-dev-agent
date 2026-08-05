# 闲时任务提示词：连库性能优化 + 能力陷阱用例构造

> 用于空闲时段执行。复制下面的提示词给 agent，在项目目录下执行。
> 两件事独立，可以分两次跑，也可以一次跑完。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里，有两件事要做。先读 `/Users/yuanbo/design-dev-agent/docs/eval-v2-design.md` 和 `/Users/yuanbo/design-dev-agent/CLAUDE.md` 了解项目约定（尤其 CLAUDE.md 第155行的 glob 禁令：文件查找必须用确定性文件名，禁止 glob 通配）。

---

### 任务一：precheck 连库性能优化（表结构本地缓存）

**背景**：precheck 的 DB 校验连库查 pg_catalog，在内网/生产 DWS 上跑 81 字段要 3 分钟（SQL 本身慢，不是网络）。需要改成"表结构本地缓存"，日常 precheck 读缓存秒级完成，缓存过期才连库刷新。

**现状**：`skills/dws-design/references/precheck.py` 的 `_check_db_schema()` 每次连库执行 pg_catalog 查询，没有缓存。

**目标改动**：

1. **新增缓存读写逻辑**（在 precheck.py 或 design-dev-shared 加一个小模块）：
   - 缓存文件路径：`{deliver}/_internal/schema_cache.json`
   - 缓存结构：
     ```json
     {
       "cached_at": "2026-08-05T18:00:00",
       "tables": {
         "ods.ods_trade_order_di": {"order_id": "varchar(64)", "cust_id": "varchar(64)"},
         "dim.dim_user": {"user_id": "bigint"}
       }
     }
     ```
   - 缓存粒度：只存"本次用到的表"的结构（schema.table → {列名: 类型}），不存全库

2. **改 `_check_db_schema()` 的查询逻辑**（命中优先）：
   - 读缓存，按 `schema.table` 找每张表的列
   - 缓存里全有且没过期（默认 24 小时，可在 db-sources.json 的 security 段配 `schema_cache_ttl_hours`）→ 纯本地对比，不连库
   - 缓存缺失或过期 → 只连库捞缺失的表，追加到缓存，再对比
   - 加 `--refresh-schema` 命令行参数：强制连库刷新全部缓存（忽略过期判断）

3. **连库捞表结构仍用 pg_catalog**（性能在"只捞缺失表"时可控，且捞完就缓存）：
   ```sql
   SELECT a.attname, format_type(a.atttypid, a.atttypmod)
   FROM pg_attribute a
   JOIN pg_class c ON a.attrelid = c.oid
   JOIN pg_namespace n ON c.relnamespace = n.oid
   WHERE n.nspname = '{schema}' AND c.relname = '{table}'
     AND a.attnum > 0 AND NOT a.attisdropped
   ```
   注意：刷新时**逐表查**（每张表一条 SQL，走精确索引），不要用 OR 拼成一条大 SQL（那是慢的根源）。

4. **日志要清晰**：报告里显示"DB 校验：缓存命中 X 表 / 连库刷新 Y 表"，让用户知道这次有没有连库。

**约束**：
- 不破坏现有 `_check_db_schema` 的校验语义（表/字段不存在仍报 error 阻断）
- 连不上库仍静默跳过（保持现有兼容）
- 缓存文件加到 .gitignore（`_internal/schema_cache.json`，产出目录本就不提交）
- tests/test_precheck_db.py 要更新：mock 的 executor 现在可能不被调用（缓存命中时），加测试覆盖"缓存命中""缓存过期连库""--refresh-schema 强制刷新"三个场景
- 全套测试必须通过（现在 214 个）

**验证**：对一个用例跑两次 precheck——第一次连库（刷新缓存），第二次纯缓存（秒级），对比耗时。如实报告两次耗时。

---

### 任务二：能力陷阱用例构造（设计 + 实现 3 个陷阱用例）

**背景**：现有评测用例（001-012）都是"正常输入"，只能测稳定性，测不了"agent 该想到的想到了吗"。要造"陷阱用例"——输入故意埋雷，断言判"该做的决策做了没"。陷阱用例放 `eval-suite/cases/`（进仓库，开发环境用）。

**方法论**（每个陷阱 = 埋雷输入 + 正确行为契约 + 断言）：
- 埋雷输入：mapping/RS 里故意留会诱导犯错的细节
- 正确行为契约：agent 应该识别什么、产出什么
- 断言：checks.yaml 配"必须有的决策"（must_actions）和"禁止出现的错误"（must_not）
- 每个陷阱配一个"干净对照版"（同样结构不埋雷），防 agent 过度警觉误报

**先造这 3 个陷阱**（按价值排，构造从易到难）：

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

**每个陷阱要产出**：
1. `eval-suite/cases/T{N}_{名}/{mapping.xlsx, RS.md}` —— 埋雷输入
2. `eval-suite/cases/T{N}_{名}_clean/{mapping.xlsx, RS.md}` —— 干净对照
3. `eval-suite/cases/T{N}_{名}/checks.yaml` —— 断言（must/must_not）
4. `eval-suite/cases/T{N}_{名}_clean/checks.yaml` —— 对照断言
5. 用 `--skip-ai` 跑一遍确认结构 OK（这些陷阱要 designer 真跑才有意义，skip-ai 只验脚本链路+断言引擎不崩）

**约束**：
- 陷阱用例编号用 T 前缀（T1/T2/T3），和 001-012 区分
- mapping.xlsx 要真实可被 preprocess 解析（参考 002 的 mapping 结构）
- 陷阱的 checks.yaml 必须能被现有 engine 跑通（assert_artifacts/assert_design/assert_sql）
- 如果发现 assert_design 缺某个断言类型（如 T3 的 field_not_mapped_from），扩展它并加测试
- 每一步如实报告：构造了什么、跑了什么、有没有报错

**验证**：对每个陷阱用例跑 `python eval-suite/v2/run.py --case T1 --skip-ai --cases-dir eval-suite/cases/`，确认断言引擎不崩、报告正常输出。如实报告结果。

---

### 收尾

两件事做完后：
1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. 如实汇报：改了哪些文件、加了哪些陷阱用例、测试结果、遇到的问题
3. 不要 git commit（等我 review）
