# DWS 编码规范

> 本规范适用于华为云 DWS (GaussDB(DWS)) 数据仓库的 ETL 代码编写

## 1. 物理设计标准

### 1.1 统一标准

| 属性 | 标准值 | 说明 |
|------|--------|------|
| 存储格式 | 列存 (COLUMN) | 默认使用列存 |
| 分布方式 | 哈希 (HASH) | 默认使用哈希分布 |
| 压缩级别 | LOW | 统一使用 LOW 压缩 |
| 分区 | 无 | 默认不分区，仅会计期场景才分区 |

### 1.2 禁止事项

| 禁止项 | 原因 |
|--------|------|
| ❌ 创建索引 | DWS 列存表不适合建索引 |
| ❌ 创建序列 | 使用业务主键，不用自增序列 |
| ❌ 使用 ROW 存储事实表 | 事实表数据量大，必须用列存 |
| ❌ 添加任何约束 | DWS 列存表不支持约束（PRIMARY KEY, NOT NULL, FOREIGN KEY, UNIQUE） |
| ❌ 设置 DEFAULT 值 | 默认值由 ETL INSERT 语句控制，DDL 不设置 DEFAULT |
| ❌ 内联 COMMENT | DWS 不支持内联 COMMENT 语法，必须使用 COMMENT ON 语句 |

---

## 2. DDL 编码规范

### 2.1 文件头注释

```sql
/* =====================================================
   表名: {schema}.{table_name}
   中文名: {table_desc}
   类型: 事实表/维度表/中间表
   步骤: {step_number} (如果是分段设计)
   创建时间: {create_date}
   说明: {description}
   ===================================================== */
```

### 2.2 建表语句规范

**⚠️ 重要规范**:

| 规范项 | 说明 |
|--------|------|
| ✅ 使用 `CREATE TABLE IF NOT EXISTS` | 幂等建表，禁止使用 `DROP TABLE IF EXISTS` |
| ✅ 指定逻辑集群 `TO GROUP` | 末尾必须指定 `TO GROUP "{logical_group}"` |
| ❌ 禁止 `DROP TABLE` | DDL 中不允许出现 DROP 语句，回退脚本单独存放 |
| ❌ 禁止 NOT NULL | DWS 列存表不支持约束，所有字段都不加 NOT NULL |
| ❌ 禁止 PRIMARY KEY | DWS 列存表不支持主键约束 |
| ❌ 禁止内联 COMMENT | 如 `col1 VARCHAR(10) COMMENT 'xxx'` 是错误语法 |
| ✅ 使用 COMMENT ON | 表注释和字段注释必须使用 `COMMENT ON TABLE/COLUMN` 语句 |

**逻辑集群自动推断规则**:

| 目标表 schema | 逻辑集群 | 区域 |
|---------------|----------|------|
| 匹配 `%drt%` | `gtoup_version1` | 实时区 |
| 其他 | `LC_DW1` | 离线区（默认） |

**DDL 文件命名规范**:

| 类型 | 创建脚本 | 回退脚本 |
|------|----------|----------|
| 建表 | `create_table_{table_name}_{owner}.sql` | `rollback_create_table_{table_name}_{owner}.sql` |
| 建视图 | `create_view_{view_name}_{owner}.sql` | `rollback_create_view_{view_name}_{owner}.sql` |

- `{owner}` 为责任人，从 mapping Excel 获取或询问用户，兜底 `etl_owner`
- `{table_name}` 不含 schema 前缀（如 `dwb_product_center_f`）
- 回退脚本存放在独立的 `04_ddl_rollback/` 目录

> DDL 模板见 [§8 DDL 模板](#8-ddl-模板)

### 2.3 注释规范

```sql
/* 表注释 */
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

/* 字段注释 (每个字段必须有注释) */
COMMENT ON COLUMN {schema}.{table_name}.{column} IS '{column_desc}';
```

**注释要求**:
- 每个表必须有表注释，每个字段必须有字段注释
- 注释内容要有意义，不能为空或重复
- 金额类字段注明单位：`订单金额，单位：元`
- 枚举类字段注明取值：`订单状态：PAID-已支付，CANCELLED-已取消`

**SQL 脚本注释**:

| 规范项 | 要求 |
|--------|------|
| 复杂SQL必须有注释 | 对功能和逻辑进行说明 |
| 语句块开始放置注释 | 解释语句块要做什么 |
| 主要部分前添加注释 | 说明功能细节 |

### 2.4 字段命名参考

| 后缀 | 类型 | 示例 |
|------|------|------|
| `_id` | BIGINT | `user_id`, `order_id` |
| `_code` | VARCHAR | `product_code`, `dept_code` |
| `_name` | VARCHAR | `product_name`, `dept_name` |
| `_amt` / `_amount` | DECIMAL(18,2) | `order_amt`, `pay_amount` |
| `_qty` | DECIMAL(18,4) | `order_qty`, `ship_qty` |
| `_cnt` | INT | `order_cnt`, `item_cnt` |
| `_rate` | DECIMAL(10,4) | `tax_rate`, `discount_rate` |
| `_time` | TIMESTAMP | `create_time`, `pay_time` |
| `_date` / `_dt` | DATE | `order_date`, `biz_dt` |
| `_flag` | NVARCHAR(1) | `del_flag` |
| `_type` | VARCHAR | `order_type`, `pay_type` |

布尔/标识字段：`is_{含义}`（如 `is_valid`）或 `{含义}_flag`（如 `del_flag`）

---

## 3. ETL 编码规范

### 3.1 文件头注释

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: 
     - {source_table1}
     - {source_table2}
   执行频率: 全量/日增量
   ===================================================== */
```

### 3.2 INSERT 语句规范

```sql
/* ✅ 正确：明确列出所有字段 */
INSERT INTO {schema}.{table_name} (
    col1, col2, col3, col4, col5,
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    col1,
    col2,
    col3,
    col4,
    col5,
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id（使用统一变量名） */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM source_table;

/* ❌ 错误：省略字段列表 */
INSERT INTO table_name SELECT * FROM source_table;
```

**⚠️ 强制规则**:

| 规则 | 说明 | 级别 |
|------|------|------|
| ✅ 删除标识过滤 | 所有源表 JOIN 时必须添加 `AND del_flag = 'N'` 或 `AND COALESCE(del_flag, 'N') = 'N'` | CRITICAL |
| ✅ 审计字段占位符 | 必须使用 `${P_CYCLE_ID}`，禁止使用空字符串或硬编码值 | CRITICAL |
| ❌ 禁止硬编码复杂字段 | 计算字段必须实现计算逻辑，禁止直接写0或常量 | MAJOR |
| ❌ 禁止无效 JOIN | JOIN 了表但未使用任何字段，应移除 | MAJOR |

**删除标识过滤示例**:
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

**审计字段占位符示例**:
```sql
/* ✅ 正确：使用统一变量 */
'${P_CYCLE_ID}' AS crt_cycle_id,
'${P_CYCLE_ID}' AS last_upd_cycle_id,

/* ❌ 错误：使用空字符串 */
'' AS crt_cycle_id,
'' AS last_upd_cycle_id,

/* ❌ 错误：硬编码 */
'BATCH_001' AS crt_cycle_id,
```

### 3.3 WITH CTE 规范

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
INSERT INTO target_table (...)
SELECT u.user_id, u.user_name, COALESCE(s.order_cnt, 0) AS order_cnt
FROM user_base u
LEFT JOIN user_stat s ON u.user_id = s.user_id;
```

### 3.4 CASE WHEN 规范

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

### 3.5 NULL 处理规范

```sql
/* 金额类字段：使用 COALESCE 设默认值 0 */
COALESCE(pay_amt, 0) AS pay_amt

/* 字符串字段：使用 COALESCE 设默认值空串 */
COALESCE(user_name, '') AS user_name

/* 计算字段：处理可能的 NULL */
CASE 
    WHEN pay_amt IS NOT NULL AND order_qty IS NOT NULL 
    THEN pay_amt / order_qty 
    ELSE NULL 
END AS unit_price
```

### 3.6 子查询取最新/第一条

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

### 3.7 聚合字段规范

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

### 3.8 复杂计算字段规范

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

### 3.9 无效 JOIN 检查

**禁止关联了表但不使用任何字段！**

```sql
/* ❌ 错误：dwd_coupon_use_f 被 JOIN 但未使用任何字段 */
LEFT JOIN sdmar.dwd_coupon_use_f cu ON a.activity_id = cu.activity_id  /* 未使用 */

/* ✅ 正确：移除无效 JOIN 或补充使用字段 */
```

### 3.10 SQL 语法规范

#### 访问对象带 Schema

```sql
/* ✅ 正确：显式指定 schema */
FROM dwd.dwd_order_f o
LEFT JOIN dim.dim_user_d u ON o.user_id = u.user_id

/* ❌ 错误：省略 schema */
FROM dwd_order_f o
LEFT JOIN dim_user_d u ON o.user_id = u.user_id
```

#### 多表 JOIN 字段别名

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

#### 禁止标量子查询

```sql
/* ❌ 错误：标量子查询（每行执行一次，性能差） */
SELECT (SELECT user_name FROM dim_user_d WHERE user_id = o.user_id) FROM dwd_order_f o

/* ✅ 正确：使用外关联 */
SELECT u.user_name FROM dwd_order_f o LEFT JOIN dim_user_d u ON o.user_id = u.user_id
```

#### 排序 NULL 值处理

```sql
/* ✅ 显式指定 NULL 排序方式 */
ORDER BY order_time DESC NULLS LAST;
ORDER BY order_time DESC NULLS FIRST;
```

#### 递归语句终结条件

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

#### 全表删除使用 TRUNCATE

```sql
TRUNCATE TABLE dwd.dwd_order_f;  /* ✅ 快速，不产生日志 */
/* DELETE FROM dwd.dwd_order_f;  ❌ 慢，产生大量日志 */
```

#### 大 IN 列表使用 UNNEST

```sql
/* ✅ IN 列表超过500个值时使用 UNNEST */
SELECT o.* FROM dwd_order_f o
INNER JOIN UNNEST(ARRAY[1, 2, 3, ..., 1000]) AS t(order_id)
    ON o.order_id = t.order_id
```

---

### 3.x 粒度对齐规范

> **设计文档的「关联安全分析」指明了每张被关联表的对齐策略，编码时必须严格按设计实现。

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

---

## 4. DWS 性能要点

> 以下为 DWS 特有的性能注意事项。通用 SQL 优化（如避免 SELECT *、WHERE 条件顺序、提前过滤等）不在本文件重复列出。

### 4.1 LEFT JOIN 过滤条件位置

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

### 4.2 避免在字段上使用函数

```sql
/* ✅ 正确：直接比较字段（利用分区裁剪） */
WHERE dt >= '2025-01-01'

/* ❌ 错误：在字段上使用函数（无法利用分区裁剪） */
WHERE DATE(dt) >= '2025-01-01'
WHERE TO_CHAR(create_time, 'YYYY-MM-DD') = '2025-01-01'
```

### 4.3 分布键与 JOIN

```sql
/* 确保关联字段分布键一致，JOIN 时不需要数据重分布
   表A: DISTRIBUTE BY HASH(order_id)
   表B: DISTRIBUTE BY HASH(order_id) */

/* 小表使用 REPLICATION (维度表)
   维度表 DISTRIBUTE BY REPLICATION → JOIN 时自动广播 */
```

---

## 5. 安全编码规范

### 数据脱敏

```sql
/* 手机号脱敏 (保留前3后4) */
CONCAT(LEFT(phone, 3), '****', RIGHT(phone, 4)) AS phone_masked

/* 邮箱脱敏 (保留前2和域名) */
CONCAT(LEFT(email, 2), '***@', SUBSTRING_INDEX(email, '@', -1)) AS email_masked

/* 身份证脱敏 (保留前4后4) */
CONCAT(LEFT(id_card, 4), '**********', RIGHT(id_card, 4)) AS id_card_masked
```

---

## 6. 代码格式规范

| 规范项 | 要求 |
|--------|------|
| 缩进 | 4 空格 |
| SELECT 字段 | 每个字段一行 |
| 关键字 | FROM/JOIN/WHERE/GROUP BY/ORDER BY 独立成行 |
| CASE WHEN | WHEN/THEN/ELSE/END 各占一行 |
| CTE | CTE 之间空一行 |
| 注释 | 复杂 SQL 必须有功能/逻辑注释 |

---

## 7. 文件命名规范

| 类型 | 格式 | 示例 |
|------|------|------|
| DDL 文件 | `{序号}_{表名}.sql` | `01_DWB_order_center_tmp1.sql` |
| ETL 文件 | `{序号}_insert_{描述}.sql` | `01_insert_tmp1.sql` |

序号从 01 开始，按执行顺序递增，DDL 和 ETL 序号对应。

---

## 8. DDL 模板

### 8.1 事实表模板

```sql
/* =====================================================
   表名: {schema}.{table_name}
   中文名: {table_desc}
   类型: 事实表
   分布键: {distribute_key}
   逻辑集群: {logical_group}
   责任人: {owner}
   创建时间: {create_date}
   ===================================================== */

CREATE TABLE IF NOT EXISTS {schema}.{table_name} (
    {pk_column}              {type},          /* 分布键字段 */
    {biz_columns}
    /* 审计字段 (标准系统字段，所有表必须包含) */
del_flag                 NVARCHAR(1),
    crt_cycle_id             BIGINT,
    last_upd_cycle_id        BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
) 
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH({distribute_key})
TO GROUP "{logical_group}";

/* 表注释 */
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

/* 字段注释 */
COMMENT ON COLUMN {schema}.{table_name}.{pk_column} IS '{pk_column_desc}';
{column_comments}
/* 审计字段注释 */
COMMENT ON COLUMN {schema}.{table_name}.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN {schema}.{table_name}.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN {schema}.{table_name}.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN {schema}.{table_name}.dw_last_update_date IS '数仓最后更新时间';
```

**对应回退脚本** (`rollback_create_table_{table_name}_{owner}.sql`):
```sql
/* =====================================================
   回退脚本: create_table_{table_name}_{owner}.sql
   对应DDL: 04_ddl/create_table_{table_name}_{owner}.sql
   执行顺序: 在对应DDL之前执行
   ===================================================== */

DROP TABLE IF EXISTS {schema}.{table_name};
```

### 8.2 维度表模板

```sql
/* =====================================================
   表名: {schema}.{table_name}
   中文名: {table_desc}
   类型: 维度表
   逻辑集群: {logical_group}
   责任人: {owner}
   创建时间: {create_date}
   ===================================================== */

CREATE TABLE IF NOT EXISTS {schema}.{table_name} (
    {natural_keys}
    {attributes}
    effective_dt            DATE,
    expiry_dt               DATE,
    is_current              CHAR(1),
    version_num             INT,
    /* 审计字段 */
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY REPLICATION
TO GROUP "{logical_group}";

/* 表注释 */
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

/* 字段注释 */
{column_comments}
```

**对应回退脚本** (`rollback_create_table_{table_name}_{owner}.sql`):
```sql
DROP TABLE IF EXISTS {schema}.{table_name};
```

### 8.3 中间表模板

```sql
/* =====================================================
   表名: {schema}.{table_name}_tmp{n}
   中文名: {table_desc}
   类型: 中间表
   分布键: {distribute_key}
   逻辑集群: {logical_group}
   责任人: {owner}
   创建时间: {create_date}
   ===================================================== */

CREATE TABLE IF NOT EXISTS {schema}.{table_name}_tmp{n} (
    {columns}
    /* 审计字段 */
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH({distribute_key})
TO GROUP "{logical_group}";

/* 表注释 */
COMMENT ON TABLE {schema}.{table_name}_tmp{n} IS '{table_desc}';

/* 字段注释 */
{column_comments}
```

**对应回退脚本** (`rollback_create_table_{table_name}_tmp{n}_{owner}.sql`):
```sql
DROP TABLE IF EXISTS {schema}.{table_name}_tmp{n};
```

---

## 9. 字段类型映射

| 源类型 | DWS 类型 | 说明 |
|--------|----------|------|
| VARCHAR2(n) | VARCHAR(n) | 变长字符串 |
| NVARCHAR2(n) | VARCHAR(n) | 变长字符串 |
| CHAR(n) | CHAR(n) | 定长字符串 |
| NUMBER(p,s) | DECIMAL(p,s) | 精确数值 |
| NUMBER | BIGINT | 整数 |
| INTEGER | INTEGER | 整数 |
| BIGINT | BIGINT | 大整数 |
| DATE | DATE/TIMESTAMP | 日期时间 |
| TIMESTAMP | TIMESTAMP | 时间戳 |
| CLOB | TEXT | 大文本 |
| BLOB | BYTEA | 二进制 |
