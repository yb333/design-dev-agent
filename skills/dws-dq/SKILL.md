---
name: dws-dq
description: >-
  DQ 检查的设计与实现。被 dws-dq-producer 加载（独立会话，闸口①窗口内并行起调）。
  契约：DQ SELECT = 违规行探测器——0 行=通过，非 0 行=告警。
  断言式（翻译）/对比式（独立重算比对）两模式，直接产 dq.json + SQL（两跳并一跳，2026-09-15）。
  ETL 加工不在此（dws-coding）；DQ 设计不再在主线 designer（2026-09 拆分）。
---

# DQ 检查设计与实现 Skill

> 收到 DQ 任务时你（dws-dq-producer）加载本 skill。**契约一句话：DQ SELECT = 违规行探测器——0 行=通过，非 0 行=告警。**

三条身份级纪律（输入隔离/歧义不拍板/检查成本自约束）在 agent.md 身份层，先于本流程。

## 1. 拿输入切片（唯一取料入口，不读 rs_input_view）

```bash
python {dws-dq 的 scripts 目录}/pick_dq_context.py --rs {build}/_internal/rs_input.json --ts {build}/ts.json --out {build}/_internal/dq_context.json
```

切片含：`dq_requirements`（RS 原文）/ `target`（F 表+business_key+字段清单含中文名）/ `source_tables` / `closure`（种子字段+确定性闭包行+**存疑行**）。

- **存疑行逐个处置**：深挖（`--query <关键词>` / `--field <字段名>` 检索 mapping 原文段）或标注歧义进 dq.json——不跳过不拍板。
- 闭包外的行按需 `--query` 补（**禁止读 mapping 全量原文**——上下文稀释+漏圈静默）。
- 引用域=**源表+目标表，禁碰 tmp**（中间表是被检实现的一部分；独立重算从源表自己算）。

## 2. 逐条设计实现（断言式/对比式），直接产两样

**格式唯一源：本 skill `assets/dq-template.json`（落盘前必读，读不到上报不自编）**。

**★ 先做必要性甄别（RS 需求不是每条都该做成 DQ）**：DQ 的域=**数据内容质量**（空值/重复/一致性/值域/逻辑复核）。识别出**结构类检查**——如"落地类型与 mapping 一致""字段是否都创建""表结构对齐"——这类已被流程内建覆盖（precheck 类型对账/assemble 字段闭合/UT 列序对账），做成 DQ 是重复检查。**决策不做 + 写进 dq.json 的 `declined` 数组**（`{rs_rule_name, reason}`，reason 写清被哪个环节覆盖），拍板权在人——闸口①看 ts.md"建议不做"段，不同意会要求你补做。**不静默丢弃**（不写 declined 又不做=漏做）。

1. **`{build}/dq.json`**——最薄形态只写 `rules` 数组（+甄别出的 `declined`；idx/sql_file 等由 assemble_dq 校验补全）：
   - **mode 判定**：声明"什么是违规"（空值/重复/阈值越界）→ 断言式（可缺省）；比对两套计算（目标vs来源一致、字段逻辑复核）→ **对比式（独立重算——你的价值所在：从源表独立实现口径，不抄被检对象）**，mode 写 "compare"。
   - **scope / check_type / rule_name 跟 RS 一致**（分类不变）；条数可拆不可少。
   - **violation_condition**：断言式=SQL 表达式（WHERE 直搬）；对比式=比对口径摘要声明（方向写清"不等/不一致即违规"）。
   - **rule_desc 必须写"违规=…"方向**（防译反）。
   - **检查成本**：随调度每天跑——聚合比对（行数/金额汇总）优先于全量明细逐行，能收时间窗就收（如当日分区）。
2. **`{build}/dq/dq_{NN}_{检查类型}.sql`**——每条一个文件（NN=rules 数组序号 01 起；检查类型清洗=非字母/数字/中文/下划线换 `_`）：
   - **WHERE/HAVING**：阈值/比例逻辑全收进来；断言式直搬自己的 violation_condition
   - **输出列 = 业务键（切片 business_key）+ 违规字段值**——断言式输出违规字段本身；对比式输出两侧值（存量值 + 重算值，列名区分如 `amount` / `expected_amount`）。不 SELECT *，不带审计字段
   - 表引用 **schema 全限定**；只碰检查对象和资产内源表
   - 参数直接写 `${参数名}`（UT 执行前替换测试值）
   - SQL 规范同 dws-coding standards：注释一律 `/* */`、标准 SQL 不猜方言

模板（断言式）：

```sql
/* DQ-空值检查: 订单金额非空 —— 违规=order_amount 为空 */
SELECT
    t.order_id,
    t.order_amount
FROM {schema}.{target_table} t
WHERE t.order_amount IS NULL;
```

模板（对比式——独立重算）：

```sql
/* DQ-一致性: 订单金额口径复核 —— 违规=存量金额与源表独立重算(pay+discount)值不等 */
SELECT
    t.order_id,
    t.amount,
    s.pay + s.discount AS expected_amount
FROM {schema}.{target_table} t
JOIN {schema}.{source_table} s ON s.order_id = t.order_id
WHERE t.amount <> s.pay + s.discount;
```

## 3. 写完即跑校验（唯一校验入口——2026-09-15 合并：check_sql --dq 已并入）

```bash
python {new-pipe 的 scripts 目录}/assemble_dq.py --ts {build}/ts.json --dq-src {build}/dq.json \
    --rs {build}/_internal/rs_input.json
```

一步完成校验（引用对账/禁 tmp/幻觉列/schema 前缀/业务键输出列）+补全+ts.md 表格渲染。不过自己改后重跑（限 3 轮）。

## 4. 交卷

`dq.json` + 全部 SQL 落盘且 assemble_dq 全绿后回报：文件数 / 断言式与对比式条数 / **歧义标注数（有必点名）** / **建议不做数（declined，有必点名）**。执行验证归 UT 的 DQ 段（0 行=过，非 0 行=告警归闸口② 人判），不要自己连库试跑。
