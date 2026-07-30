# 测试 Prompt

> 以下是在 opencode / codeagent 里测试设计开发 Agent 的 prompt。
> 先运行 `python install.py` 安装，然后复制 prompt 测试。

---

## 测试 1：dws-designer（设计 → 产出 TS）

```
帮我完成设计开发任务。

输入文件：
- mapping: @docs/templates/mapping模板.xlsx
- RS文档: @docs/templates/RS模板.md

请先用预处理脚本把 mapping + RS 合并成 rs_input.json，然后调用 dws-designer 产出 TS 制品包。

步骤：
1. 执行预处理：python skills/dws-design/references/preprocess.py --mapping docs/templates/mapping模板.xlsx --rs docs/templates/RS模板.md --output docs/output/dwl_con_pu_any_f/01_input/rs_input.json --check
2. 调用 @dws-designer：读取 docs/output/dwl_con_pu_any_f/01_input/rs_input.json，产出 ts.json + ts.md 到 docs/output/dwl_con_pu_any_f/02_design/
```

### 预期结果
- `02_design/ts.json`：以规则为核心（R0001 写入 + R0002 视图），字段内嵌规则，design_logic 是自然语言
- `02_design/ts.md`：7 章（概述/表模型/复杂度/规则详情/数据流图/调度/DQ）
- 闸口①：designer 产出后应该给人确认方向

### 检查点
- [ ] ts.json 顶层有 meta/design/rules/data_flow/dq_rules
- [ ] rules.R0001.fields 有 12 个字段 + design_logic（自然语言）
- [ ] 审计字段在 design.audit_fields，不在 fields 重复
- [ ] ts.md §4 规则详情有字段概要（不堆全部字段）

---

## 测试 2：dws-coder（TS → 产出 SQL）

> 前提：测试 1 已产出 ts.json

```
帮我完成编码任务。

调用 @dws-coder，读取 docs/output/dwl_con_pu_any_f/02_design/ts.json 的 R0001 规则，产出 SQL/DDL。

要求：
- 产出 04_ddl/create_table_dwl_con_pu_any_f.sql（建表DDL）
- 产出 05_etl/01_insert_dwl_con_pu_any_f.sql（ETL INSERT语句）
- 落盘到 docs/output/dwl_con_pu_any_f/ 下
```

### 预期结果
- `04_ddl/*.sql`：CREATE TABLE IF NOT EXISTS + 分布键 + 12业务字段 + 4审计字段
- `05_etl/*.sql`：INSERT INTO ... SELECT ... FROM（行转列用 CASE WHEN，聚合用 SUM）
- 字段加工逻辑与 ts.json 的 design_logic 一致

### 检查点
- [ ] DDL 有 IF NOT EXISTS
- [ ] ETL 没有 SELECT *
- [ ] NULL 字段有 COALESCE
- [ ] 审计字段齐全（4个）
- [ ] INSERT 字段数 = SELECT 列数

---

## 测试 3：完整流程（预处理→设计→编码）

> 手动串联测试 1 + 测试 2

```
帮我完成完整的设计开发流程。

输入：
- mapping: @docs/templates/mapping模板.xlsx
- RS文档: @docs/templates/RS模板.md

流程：
1. 预处理：解析 mapping + RS → rs_input.json
2. 设计：@dws-designer 产出 TS 制品包（ts.json + ts.md）
3. 我确认设计方向后
4. 编码：@dws-coder 按规则产出 SQL/DDL
```
