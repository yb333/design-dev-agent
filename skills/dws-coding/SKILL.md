---
name: dws-coding
description: >-
  DWS ETL 编码方法论 + SELECT 产出规范。被 dws-coder agent 加载。
  指导 coder 如何从 ts.json 规则切片产出合规的 SELECT 语句。
  DDL/INSERT/UT 由脚本处理，不在本 skill 范围。
---

## ⚠️ 文件路径规则

所有附属文件（scripts/ .py、assets/ 模板、references/ 规范）在 **skill 安装目录**下——用加载注入的 `location`（SKILL.md 绝对路径）拼 `{location所在目录}/...`，不按工作目录或 `~` 猜路径。skill_files 清单是采样（上限 10），清单没有 ≠ 不存在，以本文件提到的路径为准。

---

# DWS ETL 编码 Skill

> 本 skill 被 **dws-coder** agent 加载，提供 SELECT 编码规范和模板。
> coder 的唯一产出是 SELECT 语句。DDL/INSERT/UT 由脚本处理。

---

## 1. 编码的核心任务

把 TS 的某个规则（fields 三桶：processed 加工口径 / assign 固定值 / direct 直取串）转化为 SELECT 语句：

> **把 TS 装配成 SQL：design_logic 里的表达式直接搬用，你来搭框架、做工程**——这就是你全部的工作。

你不写 DDL（assemble_ddl.py 生成）、不拼 INSERT（run_ut.py 包装）、不做 UT（run_ut.py 检查）。

---

## 2. 编码流程

> 核心思路：**SQL 框架由你决定，工具只帮你省直取字段的机械誊写。**
> 你先看加工字段构思框架（WITH/CTE/FROM/JOIN/WHERE 怎么组织），搭好骨架后，
> 用 pick_fields 随写随查——写到哪个 JOIN，查那个表的直取字段，粘贴进 SELECT。

### 步骤 1：拿规则切片，看全貌

调 slice_ts.py 拿规则数据（**默认就是 compact**——direct 字段压一行省 70% 体积；需逐字段细节再加 `--verbose`）：

```bash
python {skill目录}/scripts/slice_ts.py --ts {ts路径} --rule {规则号}
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
- 计算字段 → **design_logic 是"SQL 表达式 +（括号口径说明）"**：
  - **表达式是唯一执行依据，原样搬进 SELECT**（调整别名/排版可以，不动逻辑）；括号说明是给闸口人的审查注，**不参与演绎**——不要按说明句的文字重新发明 SQL
  - **禁止改口径**：不加不减条件、不动 NULL/空串边界（实证案例：口径写"或空"，coder 自己加进 `in('N','')` 兜空串——原文空串应走 else，语义反转出 bug）
  - **允许机械转写**：方言函数不兼容时的保语义映射（`decode(x,a,1,d)` → `case when x=a then 1 else d end`），映射唯一无发挥空间
  - **疑义上报**：说明句与表达式明显矛盾、或表达式跑不通且改法不唯一 → 停下上报调用方，不自行取舍

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
切片**规则级** `derived_fields`（如 `{rn: "row_number() over(partition by t.id order by t.dt desc)"}`）：本表开窗/CTE 场景——把它写成 WITH（`WITH base AS (SELECT …, <定义表达式> AS rn FROM …)` 后主查询过滤 `rn=1`）或内联子查询，二选一按可读性自定；定义表达式照搬不改口径。切片 `joins` 条目若带 `derived_fields`（如 `{rn: "row_number() over(partition by org.org_id order by org.upd_time desc)"}`）：该别名不是物理表，是**带派生列的子查询**——把它写成 WITH（`WITH org AS (SELECT …, <定义表达式> AS rn FROM …)`)或内联子查询（`JOIN (SELECT …) org`），二选一按可读性自定；定义表达式照搬不改口径，join 条件里的 `org.rn = 1` 照写。**派生列不是目标表字段，不进 SELECT 输出**（输出列=切片字段清单，UT 6a 列序对账会拦多列）。

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
- 不能 SELECT *、审计字段齐全、命名规范、注释用 `/* */` 禁 `--`
- NULL 处理按业务语义判断（不是必须 COALESCE，见 §1.3）
- 方言对照表与 schema 全限定细节见 §0 / §3.2（原则见岗位定义 agents/dws-coder.md）
- **★ 投影只写本规则产出列，禁 NULL AS x 凑全列**（2026-09-15）：INSERT 列清单=结构源序∩产出列——未产出的列 INSERT 缺省即 NULL（写 NULL 补位纯冗余）；**merge_into/update 场景写 NULL = 每次增量把该列旧值清空**（SET 只 SET 产出列、其余列保留旧值才是正确语义），凑数即写错数据

### 步骤 5：静态对比

调 check_sql.py 检查 SELECT 和 ts.json 切片是否一致（表/字段/JOIN/口径引用）：

```bash
python {skill目录}/scripts/check_sql.py --sql {你的SELECT文件} --ts {ts路径} --rule {规则号}
```

不过则自己改后重对比，限3轮。

### 2.5 init 规则编码（INIT_R000X，初始化管道）

接到 `INIT_` 开头的规则时，它是初始化管道的规则（全量装载，`load_mode=truncate_table` 先删全插）。切片照常 `slice_ts --rule INIT_R0001`（slice_ts 会从 ts.init.rules 找到它）。两种工作流，看切片：

**derive 模式（init = 增量去 filter）**——切片带 `clone_source`：
- `clone_source.core_from`：指向源增量规则（如 R0001）
- `clone_source.source_sql`：源规则的 SELECT（已落盘的 `{core_from}.sql` 内容）
- `clone_source.filter`：源 SQL 里的增量 WHERE（要被换掉的）
- `clone_source.init_filter`：init 用的 WHERE（换成的，通常是 `1=1` 或全量范围）
- **你干的事**：把 `source_sql` 里的 `filter` 换成 `init_filter`（其余结构不动），写进 `INIT_R0001.sql`。就是"拿源 SQL 改 filter"。改完 check_sql 对比。
- 若 `source_sql` 为空（note 提示"源 .sql 未找到"）→ 说明增量 coder 还没跑，回报调用方（init 编码必须在增量编码之后）。

**explicit 模式（init 是独立设计，可能跟增量不像）**——切片没 `clone_source`，按常规流程走：
- 看切片的 `joins`（designer 填的核心结构，剥掉了 delta 机器）+ `field_logics`（可能从 core_from 抄来）+ `fields`，从头写 SELECT。
- 跟编码普通规则一样，只是 WHERE 用全量（无增量范围），`load_mode` 是 truncate。

> 两种都：审计字段齐全、check_sql 对比、命名 `{INIT_编号}_{简称}_truncate_table.sql`。
> init 规则不取增量范围（没有 `${BIZ_DATE_*}` 过滤），全量加工。


---

## 3. 字段加工逻辑翻译指南

| transform_type | design_logic 示例 | SQL 实现 |
|---|---|---|
| direct | "直取主表 contract_no" | `t.contract_no` |
| pivot | `SUM(CASE WHEN t.rpt_code='fbt_0001' THEN t.rpt_value_usd ELSE 0 END)`（按合同+pu汇总） | 表达式原样进 SELECT，GROUP BY 按括号说明 |
| aggregate | `SUM(CASE WHEN inv.region <> '非洲' THEN inv_amt ELSE 0 END)`（排除非洲发票） | 表达式原样进 SELECT + GROUP BY |
| assign | "审计字段，固定 'N'" | `'N'` |
| process（类型转换） | "类型转换：update_time varchar→date" | `CAST(t.update_time AS date)` / `TO_DATE(t.update_time,'YYYYMMDD')` |
| process（长度/精度） | "长度超长截取到50" / "精度收窄到2位" | `LEFT(t.col, 50)` / `ROUND(t.col, 2)` |
| process（表达式口径） | `case when nvl(a.del_flag,'N')='N' then 'N' else 'Y' end（…口径说明）` | **表达式原样搬**（含 NULL/空串边界，一个字符都不改） |

> **类型转换字段**（precheck 类型决策回写的"数据加工"字段，design_logic 标"类型转换：X→Y"）：
> 在 SELECT 里加转换函数（CAST/TO_DATE/LEFT/ROUND），**改 ETL 不改 DDL（目标类型不变）**。
> 转大类（varchar→date）用 CAST/TO_DATE；长度超长用 LEFT；精度收窄用 ROUND。

实现原则同步骤 2 的翻译纪律（搬不译/不改口径/机械转写唯一映射）；NULL 处理：**表达式里有什么用什么**——含 nvl/COALESCE 就带，不含保留 NULL（不无脑 COALESCE），括号说明明确"空值补 0"才加。

---

## 4. 审计字段（标准4个，从切片 _global 取，所有规则必带）

> **审计赋值在切片 fields 的 assign 桶里（每规则自动补齐——照桶写即可，包括中间表/tmp 规则）**。审计=每张产出表的强制标准列（tables/DDL/桶三处装配处统一补齐）——SELECT 漏带=UT 列序对账必拦。

| 字段 | 赋值 |
|---|---|
| del_flag | `'N'` 或 mapping 定义的逻辑 |
| crt_cycle_id | `'${P_CYCLE_ID}'` |
| last_upd_cycle_id | `'${P_CYCLE_ID}'` |
| dw_last_update_date | `CURRENT_TIMESTAMP` |

在 SELECT 里直接带上这 4 个字段的赋值。

### 4.1 分组键必须 SELECT 输出

聚合规则的分组键/业务主键（`_global.business_key`/`distribution_key`）不能只进 GROUP BY——它同时是 DISTRIBUTE BY 键和下游 JOIN 回来的关联键，必须 SELECT 输出。

---

## 5. 参考文档

| 文档 | 内容 |
|------|------|
| `assets/etl-templates.md` | SELECT 标准模板（各种加工模式） |
| `references/dws-coding-standards.md` | 编码规范（强制，含命名规范） |



---

## 会话与标识

task_id / 会话管理归编排者（pipe 记录并按需恢复你的会话）——你不在 SQL 产物或回报里记录任何会话标识。

## 6. 交卷自检

产出 SELECT 后**必跑 check_sql**（步骤 5）——字段覆盖/SELECT */注释规范/引用一致性它全查，不过自己改限 3 轮（fail 工作流，不预防性逐条自查）；上表翻译对照与 §4 审计要求在写时对照即可。
