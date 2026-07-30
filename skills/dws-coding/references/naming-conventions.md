# 命名规范

## 1. 分层前缀

| 前缀 | 用途 | 说明 |
|------|------|------|
| `DWD` | 接入层 | 贴源数据接入 |
| `DWB` | 明细层 | 明细数据加工 |
| `DWL` | 连接层 | 关联、宽表等连接加工 |

---

## 2. 表命名

### 格式规则

```
{前缀}_{业务对象/领域}_{数据实质简称}{后缀}

前缀:     DWD / DWB / DWL（区分层级）
数据内容: 业务对象或领域_数据实质简称（描述业务含义）
后缀:     F（物理表）/ I（视图）/ tmp+序号（临时表）
```

### 后缀说明

| 后缀 | 含义 | 说明 |
|------|------|------|
| `F` | 物理表 | 实际存储数据的表 |
| `I` | 视图 | 封装消费视图，对外提供查询接口 |
| `tmp1`, `tmp2`... | 临时表 | ETL 加工过程中的中间临时表 |

### 示例

| 表名 | 含义 |
|------|------|
| `DWB_contract_center_F` | 合同中心明细物理表 |
| `DWB_contract_center_I` | 合同中心明细消费视图 |
| `DWB_order_F` | 订单明细物理表 |
| `DWL_order_product_F` | 订单商品连接物理表 |
| `DWD_order_F` | 订单接入物理表 |

### 临时表命名

```
{前缀}_{业务对象/领域}_{数据实质简称}_tmp{n}

规则: 以目标表名前缀为基础，后缀使用 tmp+序号（从1开始）

示例（目标表为 DWB_contract_center_F）:
- DWB_contract_center_tmp1
- DWB_contract_center_tmp2
```

> **注意**: 如果用户提供了表名，临时表可参考用户提供的表名进行命名。

---

## 3. 字段命名

### 通用字段

| 字段名 | 类型 | 含义 |
|--------|------|------|
| `id` | BIGINT | 主键ID |
| `code` | VARCHAR(50) | 编码 |
| `name` | VARCHAR(200) | 名称 |
| `num` | BIGINT | 数量 |
| `amt` | DECIMAL(18,2) | 金额 |
| `rate` | DECIMAL(10,4) | 比率 |
| `qty` | DECIMAL(18,4) | 数量 |
| `dt` | DATE | 业务日期 |
| `biz_date` | DATE | 业务日期 |
| `del_flag` | NVARCHAR(1) | 删除标识 (Y/N) |
| `is_valid` | CHAR(1) | 有效标识 (Y/N) |

### 标准审计字段（所有表必须包含）

| 字段名 | 类型 | 含义 |
|--------|------|------|
| `del_flag` | NVARCHAR(1) | 删除标识，默认 'N' |
| `crt_cycle_id` | BIGINT | 创建批次ID |
| `last_upd_cycle_id` | BIGINT | 最后更新批次ID |
| `dw_last_update_date` | TIMESTAMP(0) WITHOUT TIME ZONE | 数仓最后更新时间，默认 CURRENT_TIMESTAMP |

### 类型后缀

| 后缀 | 类型 | 示例 |
|------|------|------|
| `_id` | BIGINT | `user_id`, `order_id` |
| `_code` | VARCHAR | `product_code`, `dept_code` |
| `_name` | VARCHAR | `product_name`, `dept_name` |
| `_num` | BIGINT | `order_num`, `item_num` |
| `_amt` | DECIMAL | `order_amt`, `pay_amt` |
| `_rate` | DECIMAL | `tax_rate`, `discount_rate` |
| `_qty` | DECIMAL | `order_qty`, `ship_qty` |
| `_dt` | DATE | `order_dt`, `ship_dt` |
| `_time` | TIMESTAMP | `create_time`, `pay_time` |
| `_flag` | NVARCHAR(1) | `del_flag` |
| `_type` | VARCHAR | `order_type`, `pay_type` |
| `_desc` | VARCHAR | `product_desc` |

### 布尔字段

使用 `is_` 前缀或 `_flag` 后缀：

```
is_valid      -- 是否有效
is_active     -- 是否活跃
del_flag      -- 删除标识
audit_flag    -- 审核标识
```

---

## 4. 约束命名

### 主键

```
pk_{表名}

示例: pk_DWB_order_F
```

### 外键

```
fk_{表名}_{引用表名}

示例: fk_DWB_order_F_DWD_product_F
```

### 唯一约束

```
uk_{表名}_{字段名}

示例: uk_DWB_order_F_order_code
```

### 索引

```
idx_{表名}_{字段名}

示例: idx_DWB_order_F_user_id
```

---

## 5. 注释规范

### 表注释

```sql
COMMENT ON TABLE DWB_order_F IS '订单明细事实表 - 记录每笔订单的详细信息';
```

### 字段注释

```sql
COMMENT ON COLUMN DWB_order_F.order_id IS '订单ID，主键，自增';
COMMENT ON COLUMN DWB_order_F.order_amt IS '订单金额，单位：元';
COMMENT ON COLUMN DWB_order_F.order_dt IS '订单日期，格式：YYYY-MM-DD';
```

---

## 6. DDL 模板

> **⚠️ DDL 规范要点**:
> - 使用 `CREATE TABLE IF NOT EXISTS`，禁止 `DROP TABLE`
> - 末尾必须指定 `TO GROUP "{logical_group}"`
> - 逻辑集群推断：schema 含 `drt` → `gtoup_version1`，否则 → `LC_DW1`
> - 文件命名：`create_table_{table_name}_{owner}.sql`
> - 回退脚本独立存放于 `04_ddl_rollback/` 目录

### 事实表

```sql
CREATE TABLE IF NOT EXISTS {schema}.{table_name} (
    {pk_column}              {type},          -- 分布键字段
    {biz_columns}
    -- 审计字段 (标准系统字段，所有表必须包含)
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

-- 表注释
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

-- 字段注释
COMMENT ON COLUMN {schema}.{table_name}.{pk_column} IS '{pk_column_desc}';
{column_comments}
-- 审计字段注释
COMMENT ON COLUMN {schema}.{table_name}.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN {schema}.{table_name}.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN {schema}.{table_name}.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN {schema}.{table_name}.dw_last_update_date IS '数仓最后更新时间';
```

### 维度表

```sql
CREATE TABLE IF NOT EXISTS {schema}.{table_name} (
    {natural_keys}
    {attributes}
    effective_dt            DATE,
    expiry_dt               DATE,
    is_current              CHAR(1),
    version_num             INT,
    -- 审计字段
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

-- 表注释
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

-- 字段注释
{column_comments}
```

### 中间表

```sql
CREATE TABLE IF NOT EXISTS {schema}.{table_name}_tmp{n} (
    {columns}
    -- 审计字段
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

-- 表注释
COMMENT ON TABLE {schema}.{table_name}_tmp{n} IS '{table_desc}';

-- 字段注释
{column_comments}
```

### DDL 文件命名规范

| 类型 | 创建脚本 | 回退脚本 |
|------|----------|----------|
| 建表 | `create_table_{table_name}_{owner}.sql` | `rollback_create_table_{table_name}_{owner}.sql` |
| 建视图 | `create_view_{view_name}_{owner}.sql` | `rollback_create_view_{view_name}_{owner}.sql` |

- `{owner}` 为责任人，从 mapping Excel 获取或询问用户，兜底 `etl_owner`
- `{table_name}` 不含 schema 前缀（如 `dwb_product_center_f`）
- 回退脚本存放在独立的 `04_ddl_rollback/` 目录

### 维度表

```sql
DROP TABLE IF EXISTS {schema}.{table_name};

CREATE TABLE {schema}.{table_name} (
    {natural_keys}
    {attributes}
    effective_dt            DATE,
    expiry_dt               DATE,
    is_current              CHAR(1),
    version_num             INT,
    -- 审计字段
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY REPLICATION;

-- 表注释
COMMENT ON TABLE {schema}.{table_name} IS '{table_desc}';

-- 字段注释
{column_comments}
```

### 中间表

```sql
DROP TABLE IF EXISTS {schema}.{table_name}_tmp{n};

CREATE TABLE {schema}.{table_name}_tmp{n} (
    {columns}
    -- 审计字段
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH({distribute_key});

-- 表注释
COMMENT ON TABLE {schema}.{table_name}_tmp{n} IS '{table_desc}';

-- 字段注释
{column_comments}
```
