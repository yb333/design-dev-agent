# DWS ETL 编码规范（SELECT 专属）

> **本文件仅含 SELECT 编码规范**——coder 的唯一产出是 SELECT 语句。
> DDL 规范（物理设计/建表模板/字段类型映射）已迁移到 `docs/platform/ddl-standards.md`，
> 是 `assemble_ddl.py` 的知识底座，coder 无需读。
>
> 本规范适用于华为云 DWS (GaussDB(DWS)) 数据仓库的 ETL SELECT 编写。

---

## 0. SQL 方言原则：写标准 SQL，不猜方言

**GaussDB(DWS) 官方兼容 SQL92/99/2003 标准，内核源自 PostgreSQL**——标准 SQL 在 DWS 上兼容性/适配最好，PG 家族语法是安全基线。**不确定的语法一律按 ANSI 标准写，不凭记忆猜方言**（尤其别写 Oracle 语法——它不是本内核的家）。

| 场景 | ❌ 避免的方言写法 | ✅ 标准/PG 基线写法 |
|------|-----------------|-------------------|
| 字符串聚合（拼接） | `LISTAGG(x, ',') WITHIN GROUP (ORDER BY y)`（Oracle；DWS 支持依集群版本/兼容模式而异） | `string_agg(x, ',' ORDER BY y)` |
| NULL 兜底 | `NVL(a, b)` | `COALESCE(a, b)` |
| 条件映射 | `DECODE(x, v1, r1, d)` | `CASE WHEN x = v1 THEN r1 ELSE d END` |
| 当前时间 | `sysdate` | `CURRENT_TIMESTAMP` |
| 取第一行 | `ROWNUM = 1` | `ROW_NUMBER() OVER (...) = 1`（配合显式排序） |
| 类型转换 | 隐式转换 / `TO_NUMBER` | `CAST(x AS 类型)` |

**聚合拼接必须带 ORDER BY**：`string_agg(x, ',')` 不带排序在 DWS 上**结果不稳定**（官方故障案例）——拼接序由 designer 在 design_logic 定（四要素），照写。

**类型转换细则**（版本无关写法；爆错只发生在**字符→数值/日期**方向，反方向安全）：

- 显式 `CAST(x AS 类型)` 首选；`::` 可用但官方未文档化，次选
- 字符→数值，源可能有脏数据的加守卫（守不住就是 `invalid input syntax` 爆错）：
  `CASE WHEN x ~ '^[0-9]+(\.[0-9]+)?$' THEN CAST(x AS numeric) END`；只防空串用 `CAST(NULLIF(trim(x),'') AS numeric)`
- 带小数的字符串直接转整数会爆错——中转 numeric：`CAST(CAST(x AS numeric) AS int8)`；注意 numeric→整数是**四舍五入**不是截断
- 字符→日期必须带显式格式 `to_date(x, 'YYYYMMDD')`——不写格式走会话参数（nls_date_format），环境漂移即错位；格式与源字符串严格对齐
- 数值/日期→字符用 `to_char(x, fmt)` 定格式（裸 CAST float→字符可能出科学计数法）
- 目标长度收窄（含字节→字符语义变化，如 varchar2(100 byte)→nvarchar2(30 char)）：加安全处理=按**字符**截取 `SUBSTR(x, 1, n)`（不置 NULL——尾部丢失由 precheck [截断披露] warn 在闸口①披露，业务不可接受才退 BA 改长度）
- JOIN/比较键两侧类型在源头对齐，不靠隐式转换（性能劣化+语义漂移）——键类型不齐回报调用方，不自作主张 CAST 凑合

---

## 1. SELECT 字段规范

### 1.1 字段别名

每个输出字段必须用 `AS` 显式命名，且和切片的 target_field 一致：
```sql
/* ✅ 明确别名（check_sql 靠 AS 识别字段覆盖） */
t.contract_no AS contract_no
/* ❌ 隐式，check_sql 检查不到，可能漏判 */
t.contract_no
```

### 1.2 不能 SELECT *

```sql
/* ✅ 列出字段 */
SELECT t.contract_no, t.amount
/* ❌ 禁止 */
SELECT t.*
```

### 1.3 NULL 处理

**该不该 COALESCE、用什么默认值，是业务语义判断，不是铁律**——业务诉求就是要 NULL 时（可选字段没值、未知状态），保留 NULL 才对，硬塞默认值反而错。根据字段语义决定：

```sql
/* 金额类：业务上 NULL = 0，COALESCE 合理 */
COALESCE(t.amount, 0) AS amount
/* LEFT JOIN 可能失败的：看业务要不要保留关联失败的信号 */
COALESCE(inv_agg.total, 0) AS total   /* 取0 = 当作没数据 */
inv_agg.total AS total                /* 不 COALESCE = 保留"关联失败"的 NULL 信号 */
```

判断参考：
- 金额/计数类（NULL 在业务里等于 0）→ COALESCE(..., 0)
- 主键/外键（NULL→0 会掩盖 LEFT JOIN 关联失败）→ 不 COALESCE
- 状态/标识字段（NULL 可能有业务含义，如"未知"）→ 按业务口径
- 可选字段（没值就是 NULL）→ 保留 NULL

### 1.4 聚合字段规范

```sql
/* ✅ 正确：使用 COUNT(1) 统计行数，COALESCE 处理聚合 NULL */
SELECT 
    user_id,
    COUNT(1) AS order_cnt,
    COALESCE(SUM(pay_amt), 0) AS total_amt
FROM dwd_order_f
GROUP BY user_id

/* ❌ 错误：使用 COUNT(*) 或聚合结果可能为 NULL */
SELECT user_id, COUNT(*) AS order_cnt, SUM(pay_amt) AS total_amt
FROM dwd_order_f
GROUP BY user_id
```

### 1.5 复杂计算字段规范

**禁止硬编码复杂计算字段！**

```sql
/* ✅ 正确：实现完整的计算逻辑 */
CASE
    WHEN COALESCE(order_stats.order_cnt, 0) = 0 THEN 0
    ELSE COALESCE(order_stats.new_user_cnt, 0) * 100.0 / order_stats.order_cnt
END AS new_user_rate

/* ❌ 错误：直接硬编码 0 */
0 AS new_user_rate
```

**处理原则**:
1. 优先实现计算逻辑
2. 数据来源缺失时，在待确认项中说明
3. 禁止无说明直接硬编码

---

## 2. JOIN 规范

### 2.1 删除标识过滤

所有源表 JOIN 时必须添加 `del_flag = 'N'` 过滤：

```sql
/* ✅ 正确：所有源表都添加删除标识过滤 */
FROM sdmar.dwd_activity_f a
WHERE a.del_flag = 'N'                    /* 主表过滤 */

LEFT JOIN dim.dim_activity_type_f at 
    ON a.activity_type = at.type_code 
    AND at.del_flag = 'N'                /* 维度表过滤 */

LEFT JOIN dim.dim_coupon_f c 
    ON a.activity_id = c.activity_id 
    AND c.del_flag = 'N'                 /* 维度表过滤 */

/* ❌ 错误：未添加删除标识过滤 */
FROM sdmar.dwd_activity_f a
LEFT JOIN dim.dim_activity_type_f at ON a.activity_type = at.type_code
```

> codegen_direct.py 生成的 FROM/JOIN 骨架会自动带 del_flag 过滤。

### 2.2 无效 JOIN 检查

**禁止关联了表但不使用任何字段！**

```sql
/* ❌ 错误：dwd_coupon_use_f 被 JOIN 但未使用任何字段 */
LEFT JOIN sdmar.dwd_coupon_use_f cu ON a.activity_id = cu.activity_id  /* 未使用 */

/* ✅ 正确：移除无效 JOIN 或补充使用字段 */
```

### 2.3 多表 JOIN 字段别名

```sql
/* ✅ 正确：所有字段都带表别名 */
SELECT o.order_id, u.user_name
FROM dwd.dwd_order_f o
LEFT JOIN dim.dim_user_d u ON o.user_id = u.user_id

/* ❌ 错误：字段缺少表别名 */
SELECT order_id, user_name FROM dwd_order_f o LEFT JOIN dim_user_d u ...
```

**强制规则**：
- 多表 JOIN 时，SELECT/WHERE 字段**必须**带表别名
- 同一查询中，不同表**必须**使用不同别名

### 2.4 禁止标量子查询

```sql
/* ❌ 错误：标量子查询（每行执行一次，性能差） */
SELECT (SELECT user_name FROM dim_user_d WHERE user_id = o.user_id) FROM dwd_order_f o

/* ✅ 正确：使用外关联 */
SELECT u.user_name FROM dwd_order_f o LEFT JOIN dim_user_d u ON o.user_id = u.user_id
```

### 2.5 子查询取最新/第一条

一对多关系使用 ROW_NUMBER：

```sql
LEFT JOIN (
    SELECT 
        order_id, pay_id, pay_amt, pay_time,
        ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY pay_time DESC) AS rn
    FROM dwd_payment_f
    WHERE pay_status = 'SUCCESS'
) pay ON o.order_id = pay.order_id AND pay.rn = 1
```

> join_safety 标记 join_key_unique=false 的表，codegen_direct.py 会生成对应的 CTE 骨架。

---

## 3. SQL 语法规范

### 3.1 CASE WHEN 规范

```sql
/* ✅ 正确：有 ELSE 分支 */
CASE order_status
    WHEN 'PAID' THEN '已支付'
    WHEN 'SHIPPED' THEN '已发货'
    ELSE '其他'
END AS order_status_name

/* ❌ 错误：缺少 ELSE */
CASE order_status
    WHEN 'PAID' THEN '已支付'
END AS order_status_name
```

### 3.2 访问对象带 Schema

```sql
/* ✅ 正确：显式指定 schema */
FROM dwd.dwd_order_f o
LEFT JOIN dim.dim_user_d u ON o.user_id = u.user_id

/* ❌ 错误：省略 schema */
FROM dwd_order_f o
LEFT JOIN dim_user_d u ON o.user_id = u.user_id
```

**每张表都必须有 schema**——包括我们自产的中间表（tmp，与目标表同 schema；切片 source_tables 的伪源表已带）。check_sql 静态查裸表名引用（CTE 名豁免）。

### 3.3 排序 NULL 值处理

```sql
/* ✅ 显式指定 NULL 排序方式 */
ORDER BY order_time DESC NULLS LAST;
ORDER BY order_time DESC NULLS FIRST;
```

### 3.4 递归语句终结条件

```sql
/* ✅ 正确：有明确的终结条件 */
WITH RECURSIVE cte AS (
    SELECT id, parent_id, 1 AS level FROM tree_table WHERE parent_id IS NULL
    UNION ALL
    SELECT t.id, t.parent_id, c.level + 1
    FROM tree_table t INNER JOIN cte c ON t.parent_id = c.id
    WHERE c.level < 10  /* 终结条件 */
)
SELECT * FROM cte;
```

### 3.5 全表删除使用 TRUNCATE

```sql
TRUNCATE TABLE dwd.dwd_order_f;  /* ✅ 快速，不产生日志 */
/* DELETE FROM dwd.dwd_order_f;  ❌ 慢，产生大量日志 */
```

### 3.6 大 IN 列表使用 UNNEST

```sql
/* ✅ IN 列表超过500个值时使用 UNNEST */
SELECT o.* FROM dwd_order_f o
INNER JOIN UNNEST(ARRAY[1, 2, 3, ..., 1000]) AS t(order_id)
    ON o.order_id = t.order_id
```

---

## 4. CTE 与粒度对齐

### 4.1 WITH CTE 规范

复杂查询使用 CTE 提高可读性：

```sql
WITH 
/* 用户基础信息 */
user_base AS (
    SELECT user_id, user_name
    FROM dim_user_f
    WHERE del_flag = 'N'
),

/* 用户订单统计 */
user_stat AS (
    SELECT user_id, COUNT(1) AS order_cnt
    FROM dwd_order_f
    GROUP BY user_id
)
SELECT u.user_id, u.user_name, COALESCE(s.order_cnt, 0) AS order_cnt
FROM user_base u
LEFT JOIN user_stat s ON u.user_id = s.user_id;
```

### 4.2 粒度对齐规范

> **设计文档的「关联安全分析」指明了每张被关联表的对齐策略，编码时必须严格按设计实现。**

**核心规则**：
1. **禁止粒度不一致时直接 JOIN** — 被关联表粒度比主表更细时，必须先用 CTE/子查询收敛
2. **对照设计文档实现** — 设计文档标记「先聚合再关联」的表，代码中必须有对应 CTE
3. **粒度对齐方式**：
   - GROUP BY 收敛：被关联表按主表粒度聚合后关联
   - ROW_NUMBER 去重：一对多关系取最新/第一条后关联
   - 直接关联：粒度一致或被关联表粒度更粗时可直接 JOIN

```sql
/* ❌ 错误：主表按 product_id 粒度，直接 JOIN 粒度更细的 (product_id, dt) 表 */
SELECT gc.product_id, gc.attr1, sd.sales_amt
FROM grain_changed gc
LEFT JOIN dwd_sales_detail sd ON gc.product_id = sd.product_id
/* 数据膨胀！一个商品对应多天销售记录 */

/* ✅ 正确：先收敛被关联表粒度，再安全关联 */
WITH aligned_sales AS (
    SELECT product_id, SUM(sales_amt) AS sales_amt
    FROM dwd_sales_detail
    WHERE del_flag = 'N'
    GROUP BY product_id
)
SELECT gc.product_id, gc.attr1, als.sales_amt
FROM grain_changed gc
LEFT JOIN aligned_sales als ON gc.product_id = als.product_id
```

> codegen_direct.py 对 join_safety 标记 join_key_unique=false 的表生成 CTE 骨架，
> 收敛逻辑（GROUP BY 哪些字段、ROW_NUMBER 按什么排序）由你按 join_safety.strategy 填。

---

## 5. DWS 性能要点

> 以下为 DWS 特有的性能注意事项。通用 SQL 优化（如避免 SELECT *、WHERE 条件顺序、提前过滤等）不在本文件重复列出。

### 5.1 LEFT JOIN 过滤条件位置

```sql
/* ✅ 正确：过滤条件在 WHERE 中 */
FROM order_f o
LEFT JOIN payment_f p ON o.order_id = p.order_id
WHERE o.order_status = 'PAID'
  AND p.pay_status = 'SUCCESS'

/* ❌ 错误：过滤条件在 ON 中 (LEFT JOIN 会失效) */
FROM order_f o
LEFT JOIN payment_f p ON o.order_id = p.order_id 
    AND p.pay_status = 'SUCCESS'  /* 这会导致 LEFT JOIN 结果不符合预期 */
WHERE o.order_status = 'PAID'
```

### 5.2 避免在字段上使用函数

```sql
/* ✅ 正确：直接比较字段（利用分区裁剪） */
WHERE dt >= '2025-01-01'

/* ❌ 错误：在字段上使用函数（无法利用分区裁剪） */
WHERE DATE(dt) >= '2025-01-01'
WHERE TO_CHAR(create_time, 'YYYY-MM-DD') = '2025-01-01'
```

### 5.3 分布键与 JOIN

```sql
/* 确保关联字段分布键一致，JOIN 时不需要数据重分布
   表A: DISTRIBUTE BY HASH(order_id)
   表B: DISTRIBUTE BY HASH(order_id) */

/* 小表使用 REPLICATION (维度表)
   维度表 DISTRIBUTE BY REPLICATION → JOIN 时自动广播 */
```

---

## 6. 安全编码（数据脱敏）

```sql
/* 手机号脱敏 (保留前3后4) */
CONCAT(LEFT(phone, 3), '****', RIGHT(phone, 4)) AS phone_masked

/* 邮箱脱敏 (保留前2和域名) */
CONCAT(LEFT(email, 2), '***@', SUBSTRING_INDEX(email, '@', -1)) AS email_masked

/* 身份证脱敏 (保留前4后4) */
CONCAT(LEFT(id_card, 4), '**********', RIGHT(id_card, 4)) AS id_card_masked
```

---

## 7. 代码格式规范

| 规范项 | 要求 |
|--------|------|
| 缩进 | 4 空格 |
| SELECT 字段 | 每个字段一行 |
| 关键字 | FROM/JOIN/WHERE/GROUP BY/ORDER BY 独立成行 |
| CASE WHEN | WHEN/THEN/ELSE/END 各占一行 |
| CTE | CTE 之间空一行 |
| 注释 | 复杂 SQL 必须有功能/逻辑注释，**统一用 `/* */` 块注释**（见下） |

### 注释规范（★ 强制）

**所有注释一律使用 `/* */` 块注释，禁止使用 `--` 行注释。** check_sql 会检测并报错。

```sql
/* ✅ 正确：块注释 */
/* 文件头/CTE用途/字段说明/行内标注 都用 /* */ */
COALESCE(t.amount, 0) AS amount   /* 金额默认0 */

/* ❌ 错误：禁止行注释 */
-- 金额默认0
COALESCE(t.amount, 0) AS amount   -- 金额默认0
```

各场景的注释要求：
- **文件头**：`/* ===== ... ===== */` 多行块注释（规则名/目标表/来源/写入方式/设计意图）
- **CTE 用途**：每个 CTE 上方用 `/* CTE 名: 用途说明 */` 标注
- **加工字段**：每个加工字段用 `/* 注释 */` 说明加工逻辑（直取字段不用注释）
- **行内标注**：简短说明用 `/* xxx */` 行尾块注释

---

## 8. 文件命名规范

| 类型 | 格式 | 示例 |
|------|------|------|
| ETL 文件 | `R{编号}_{规则名简称}_{写入方式}.sql` | `R0001_订单汇总_truncate_table.sql` |

- 编号：从切片的 rule_code 取（如 R0001）
- 规则名简称：从 rule_name 取关键词（去掉空格，简短）
- 写入方式：从 load_mode 取（truncate_table / no_delete / truncate_partition / merge_into 等）
