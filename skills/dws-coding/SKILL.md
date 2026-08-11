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

> 核心思路：**SQL 框架由你决定，工具只帮你省直取字段的机械誊写。**
> 你先看加工字段构思框架（WITH/CTE/FROM/JOIN/WHERE 怎么组织），搭好骨架后，
> 用 pick_fields 随写随查——写到哪个 JOIN，查那个表的直取字段，粘贴进 SELECT。

### 步骤 1：拿规则切片，看全貌

调 slice_ts.py 拿规则数据（大规则用 `--compact` 省体积）：

```bash
python {skill目录}/scripts/slice_ts.py --ts {ts路径} --rule {规则号} --compact
```

或先用 pick_fields 看字段分布（哪个源表多少直取字段、有哪些加工字段）：

```bash
python {skill目录}/scripts/pick_fields.py --ts {ts路径} --rule {规则号} --list
```

### 步骤 2：看加工字段，构思 SQL 框架 ★

**加工字段决定框架**——读切片的加工字段 design_logic（slice_ts 输出或 `pick_fields --field <字段>`），
构思：需要哪些 CTE？怎么 JOIN？哪里要 GROUP BY？哪些表要先收敛？

加工字段翻译：
- `aggregate` → `SUM(...)` / `COUNT(...)` + GROUP BY
- `pivot` → `SUM(CASE WHEN ...)`
- CTE 收敛 → 按 join_safety.strategy（GROUP BY 收敛 / ROW_NUMBER 去重）
- 计算字段 → 按 design_logic 实现完整逻辑（禁止硬编码 0）

搭好框架：WITH...CTE...SELECT(...)FROM...JOIN...WHERE...

### 步骤 3：随写随查，填直取字段 ★

框架搭好后，写 SELECT 时遇到直取字段，**用 pick_fields 随取随用**——
写到某个 JOIN 的表，查那个表的直取字段，粘贴进 SELECT：

```bash
# 写到 dim_user_f duf 这个 JOIN → 取 duf 的直取字段
python {skill目录}/scripts/pick_fields.py --ts {ts路径} --rule {规则号} --alias duf

# 不确定某个字段是直取还是加工 → 查详情
python {skill目录}/scripts/pick_fields.py --ts {ts路径} --rule {规则号} --field order_status
```

`--alias` 返回的字段行是纯取值表达式（`别名.字段 AS 目标字段`），**不含 COALESCE**——该不该 COALESCE、用什么默认值由你判断（金额 NULL→0 合理，主键 NULL→0 会掩盖关联失败，状态字段 NULL 可能有含义）。
**SQL 框架（FROM/JOIN/WHERE/CTE/del_flag 过滤/聚合）完全由你决定**——工具不生成这些，因为它们取决于加工字段和关联逻辑。

### 2.4 pick_fields 场景速查

不知道该用哪个命令时，按场景对照：

| 你在做什么 | 用什么命令 |
|---|---|
| 刚拿到规则，想看全貌（哪些源表、各多少直取字段、有哪些加工字段） | `--list` |
| 已搭好框架，开始写某个 `LEFT JOIN xxx 别名`，要这个表的直取字段 | `--alias 别名` |
| 不确定某字段是直取还是加工，或想看它的 design_logic | `--field 字段名` |
| 写加工字段前，确认 design_logic 引用的字段（如 user_id/create_time）在不在源表里 | `--table-fields 别名` |
| 字段少（2-3个）或你很熟悉这张表 | 直接手写，不必走工具 |

注意：
- `--alias` 输出的字段行**带尾逗号**，最后一个字段贴进 SELECT 后记得去掉逗号
- alias 打错了不报错，会列出所有合法别名；字段名打错了会给模糊匹配建议
- 同表多别名场景（一张表按不同关联逻辑 JOIN 多次），每个别名单独查
- `--table-fields` 读 `_internal/schema_cache.json`（precheck 连库时产出）；未连库时提示不阻断，凭 design_logic 写

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

> 工具脚本（slice_ts.py / **pick_fields.py** / check_sql.py / dws_db.py / assemble_ddl.py / run_ut.py）在 `scripts/` 下，agent 通过 bash 调用。

---

## 6. 产出检查清单

产出 SELECT 前自检：
- [ ] SELECT 覆盖切片里所有目标字段（不漏字段）
- [ ] 每个 aggregate/计算字段实现了完整逻辑（禁止硬编码 0）
- [ ] 审计字段 4 个带上（del_flag/crt_cycle_id/last_upd_cycle_id/dw_last_update_date）——**中间表/tmp 规则也要带**
- [ ] direct 字段的 COALESCE 处理正确（按字段语义判断：金额→0、主键/外键不 COALESCE、状态字段按需）
- [ ] JOIN 条件和切片的 joins 一致
- [ ] 不能 SELECT *
- [ ] NULL 字段有 COALESCE
- [ ] 字段名符合命名规范
- [ ] check_sql.py 静态对比通过
