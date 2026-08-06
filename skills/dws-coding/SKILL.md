---
name: dws-coding
description: >-
  DWS ETL 编码方法论 + SELECT 产出规范。被 dws-coder agent 加载。
  指导 coder 如何从 ts.json 规则切片产出合规的 SELECT 语句。
  DDL/INSERT/UT 由脚本处理，不在本 skill 范围。
---

## ⚠️ 文件路径规则（必须遵守）

本 skill 的所有文件（scripts/ 下的脚本、assets/ 下的模板、references/ 下的指导知识）都在 **skill 安装目录** 下，不在你的工作目录下。

### 怎么拿到 skill 安装目录的真实路径

加载 skill 后，opencode 会注入 skill 的 `location`（SKILL.md 的绝对路径）和 `<skill_files>` 文件列表。**用这些注入的路径**找文件——location 的同级目录下分三类：
- `scripts/`：脚本（.py）
- `assets/`：模板（带 template/example 后缀，如 etl-templates.md、配置 example）
- `references/`：指导知识（编码规范等文档）

### 读取文件

用注入的 location 路径拼目录，例如：
- `{location所在目录}/assets/etl-templates.md`（模板）
- `{location所在目录}/references/dws-coding-standards.md`（编码规范）

**绝对不要**按当前工作目录或 `~` 去拼路径——跨平台会出错。

---

# DWS ETL 编码 Skill

> 本 skill 被 **dws-coder** agent 加载，提供 SELECT 编码规范和模板。
> coder 的唯一产出是 SELECT 语句。DDL/INSERT/UT 由脚本处理。

---

## 1. 编码的核心任务

把 TS 的某个规则（自然语言口径）转化为 SELECT 语句：

> **把 design_logic（自然语言）翻译成 SQL（套规范）——这就是你全部的工作。**

你不写 DDL（assemble_ddl.py 生成）、不拼 INSERT（run_ut.py 包装）、不做 UT（run_ut.py 检查）。

---

## 2. 编码流程

### 步骤 1：拿规则切片

调 slice_ts.py 拿到自己负责的规则的数据（不读整个 ts.json）：

```bash
python {skill目录}/scripts/slice_ts.py --ts {ts路径} --rule {规则号}
```

### 步骤 2：理解规则

从切片读取：
- target_table（产出表）/ source_tables / joins / ctes / grain
- fields 列表（每个字段的 design_logic + transform_type + source_fields）
- join_safety（关联安全策略，如"取最新有效行"）

### 步骤 3：写 SELECT

把每个字段的 design_logic 翻译成 SQL 表达式：
- `direct` → `t.contract_no`
- `pivot` → `SUM(CASE WHEN t.rpt_code='fbt_0001' THEN t.rpt_value_usd ELSE 0 END)`
- `aggregate` → `SUM(inv_mtr.inv_inst_amt_usd)` + GROUP BY
- `assign` → `'N'`（审计字段固定值）

JOIN 条件从切片的 joins 取。
关联安全策略（不唯一的 JOIN 键）体现在 CTE 或子查询里（先收敛再关联）。
审计字段从切片 `_global.audit_fields` 取（4 个标准赋值）。

详见 `assets/etl-templates.md` 的 SELECT 模板。

### 步骤 4：套规范

详见 `references/dws-coding-standards.md`：
- 不能 SELECT *、NULL 必须 COALESCE、审计字段齐全、命名规范

### 步骤 5：静态对比

调 check_sql.py 检查 SELECT 和 ts.json 切片是否一致（表/字段/JOIN）。
不过则自己改后重对比，限3轮。

---

## 3. 字段加工逻辑翻译指南

| transform_type | design_logic 示例 | SQL 翻译 |
|---|---|---|
| direct | "直取主表 contract_no" | `t.contract_no` |
| pivot | "rpt_code='fbt_0001' 对应金额，按合同+pu汇总" | `SUM(CASE WHEN t.rpt_code='fbt_0001' THEN t.rpt_value_usd ELSE 0 END)` |
| aggregate | "对金额求和，排除非洲发票" | `COALESCE(SUM(inv_amt), 0)` + NOT EXISTS 过滤 |
| assign | "审计字段，固定 'N'" | `'N'` |

**翻译原则**：
- design_logic 描述"算什么口径"，SQL 实现"怎么算"
- NULL 处理：COALESCE(xxx, 0) / COALESCE(xxx, '')
- 不改变业务口径，只做技术翻译

---

## 4. 审计字段（标准4个，从切片 _global 取，所有规则必带）

> **每条规则的 SELECT 都必须带这 4 个审计字段——包括中间表/临时表(tmp)规则。**
> 原因：`assemble_ddl.py` 会给每张产出表（含 tmp 中间表）追加审计列，
> 若 SELECT 漏带，会导致 SELECT 列数 < DDL 列数，INSERT 时列不匹配。
> `_global.audit_fields` 在所有规则切片里都存在，不要因为"这是中间表"就省略。

| 字段 | 赋值 |
|---|---|
| del_flag | `'N'` 或 mapping 定义的逻辑 |
| crt_cycle_id | `'${P_CYCLE_ID}'` |
| last_upd_cycle_id | `'${P_CYCLE_ID}'` |
| dw_last_update_date | `CURRENT_TIMESTAMP` |

在 SELECT 里直接带上这 4 个字段的赋值。

### 4.1 业务主键 / 分组键也必须出现在字段列表里

聚合类规则（`grain.change == 多行聚合`）的**分组键/业务主键**（见 `_global.business_key` /
`_global.distribution_key`，如 `user_id`、`product_id`）必须作为 SELECT 的一个字段输出
（`dof.user_id AS user_id`），原因：
- 它是目标表的 `DISTRIBUTE BY` 键和下游规则 `JOIN` 回来的关联键；
- 若只放进 `GROUP BY` 而不 SELECT，DDL 会生成一个表里没有的列名做分布键，且下游无法关联。

即：**GROUP BY 的键，必须同时 SELECT 出来。**

---

## 5. 参考文档

| 文档 | 内容 |
|------|------|
| `assets/etl-templates.md` | SELECT 标准模板（各种加工模式） |
| `references/dws-coding-standards.md` | 编码规范（强制，含命名规范） |

> 工具脚本（slice_ts.py / check_sql.py / dws_db.py / assemble_ddl.py / run_ut.py）在 `scripts/` 下，agent 通过 bash 调用。

---

## 6. 产出检查清单

产出 SELECT 前自检：
- [ ] SELECT 覆盖切片里所有目标字段（不漏字段）
- [ ] 每个字段有对应的 SQL 表达式（翻译自 design_logic）
- [ ] 审计字段 4 个带上（从 _global.audit_fields 取，**中间表/tmp 规则也要带**）
- [ ] JOIN 条件和切片的 joins 一致
- [ ] 不能 SELECT *
- [ ] NULL 字段有 COALESCE
- [ ] 字段名符合命名规范
- [ ] check_sql.py 静态对比通过
