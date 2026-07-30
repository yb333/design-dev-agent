---
name: dws-coding
description: >-
  DWS ETL 编码方法论 + 规范 + 模板。被 dws-coder agent 加载。
  指导如何从 TS 的规则切片产出合规的 SQL/DDL。
---

# DWS ETL 编码 Skill

> 本 skill 被 **dws-coder** agent 加载，提供编码规范和模板。
> TS 格式定义见 `docs/specs/ts-format.md`。

---

## 1. 编码的核心任务

把 TS 的某个规则（自然语言口径）转化为可执行的合规 SQL：
- **DDL**：建表语句（IF NOT EXISTS + 分布键 + 列存）
- **ETL**：INSERT INTO ... SELECT ...（从源表加工写入）

本质是——**把 design_logic（自然语言）翻译成 SQL（套规范）**。

---

## 2. 编码流程

### 步骤 1：理解规则
- read ts.json，找到要编码的规则（R0001 等）
- 读取该规则的 target_table / source_tables / joins / ctes / grain
- 读取该规则的 fields 列表（每个字段的 design_logic + transform_type + source_fields）

### 步骤 2：写 DDL
- 目标表/中间表的建表语句
- 字段名+类型从 ts.json 的 fields 取
- 审计字段从 design.audit_fields 取（4个标准字段）
- 分布键从 design.distribution_key 取
- 详见 `references/etl-templates.md` 的 DDL 模板

### 步骤 3：写 ETL
- INSERT INTO target SELECT ... FROM sources
- 每个字段的加工逻辑：把 design_logic 翻译成 SQL 表达式
  - direct（直取）→ 直接取源字段
  - pivot（行转列）→ SUM(CASE WHEN ...)
  - aggregate（聚合）→ SUM/GROUP BY
  - assign（赋值）→ 固定值/占位符
- JOIN 条件从规则的 joins 取
- CTE 从规则的 ctes 取
- WHERE/GROUP BY 从 grain 和 join_safety 推导
- 详见 `references/etl-templates.md` 的 ETL 模板

### 步骤 4：套规范
- 详见 `references/dws-coding-standards.md`
- 核心：不能 SELECT *、NULL 要 COALESCE、审计字段齐全、命名规范

### 步骤 5：静态检查
- 调 sql_validator 脚本检查语法+规范
- 调 validate_ddl 检查 DDL 字段类型与 TS 一致

### 步骤 6：执行验证（螺旋回路）
- 调执行脚本跑 SQL（连开发环境数据库）
- 拿结构化结果（成功/失败+报错+行数+主键检查）
- 失败→理解报错→改SQL→再跑

---

## 3. 字段加工逻辑翻译指南

| transform_type | design_logic 示例 | SQL 翻译 |
|---|---|---|
| direct | "直取主表 contract_no" | `t.contract_no` |
| direct | "直取 currency_code，重命名 tc_code" | `t.currency_code AS tc_code` |
| pivot | "rpt_code='fbt_0001' 对应金额，按合同+pu汇总" | `SUM(CASE WHEN t.rpt_code='fbt_0001' THEN t.rpt_value_usd ELSE 0 END)` |
| aggregate | "对金额求和，排除非洲发票" | `SUM(inv_mtr.inv_inst_amt_usd)` + NOT EXISTS 过滤 |
| assign | "审计字段，固定 'N'" | `'N'` |

**翻译原则**：
- design_logic 描述"算什么口径"，SQL 实现"怎么算"
- NULL 处理：COALESCE(xxx, 0) / COALESCE(xxx, '')
- 不改变业务口径，只做技术翻译

---

## 4. 审计字段（标准4个）

| 字段 | 类型 | 默认值 |
|---|---|---|
| del_flag | nvarchar(1) | 'N' |
| crt_cycle_id | bigint | '${P_CYCLE_ID}' |
| last_upd_cycle_id | bigint | '${P_CYCLE_ID}' |
| dw_last_update_date | timestamp(0) without time zone | CURRENT_TIMESTAMP |

从 ts.json 的 `design.audit_fields` 取，不自己编。

---

## 5. 参考文档

| 文档 | 内容 |
|------|------|
| `references/dws-coding-standards.md` | 编码规范（强制） |
| `references/etl-templates.md` | DDL/ETL 标准模板 |
| `references/naming-conventions.md` | 命名规范 |
| `docs/specs/ts-format.md` | TS 格式（读取规则的结构） |

---

## 6. 产出检查清单

产出 SQL 前自检：
- [ ] DDL 有 IF NOT EXISTS
- [ ] DDL 有分布键（DISTRIBUTE BY HASH）
- [ ] ETL 不能 SELECT *
- [ ] NULL 字段有 COALESCE
- [ ] 审计字段齐全（4个）
- [ ] INSERT 字段数 = SELECT 列数
- [ ] 字段名符合命名规范
- [ ] 静态检查（sql_validator）通过
