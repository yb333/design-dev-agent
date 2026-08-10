# DWS DDL 规范（平台知识底座）

> **定位**：本文件是 `assemble_ddl.py` 的平台知识底座，记录 DWS（华为云 GaussDB(DWS)）的物理设计标准和 DDL 模板。
> **读者**：脚本开发者（修改 `assemble_ddl.py` 时对照本文件）、需要理解 DDL 生成规则的开发者。
> **coder 无需读**——coder 只写 SELECT，不碰 DDL。DDL 由 `assemble_ddl.py` 根据本文件的规则自动生成。
>
> 注：本文件的内容已在 `assemble_ddl.py` 中硬编码实现。修改脚本时以此为准，保持文档与代码同步。

---

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

**逻辑集群自动推断规则**（`assemble_ddl.py` 的 `infer_logical_group` 实现）:

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
