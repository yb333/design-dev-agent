# DWS 最佳实践

> **物理设计标准**（统一标准）:
> - 存储格式: 列存 (ORIENTATION = COLUMN)
> - 分布方式: 哈希 (DISTRIBUTE BY HASH)
> - 压缩级别: LOW
> - 分区: 默认无，仅会计期场景才按会计期分区

## 1. 分布键 (Distribute Key)

### 选择原则

```
优先级:
1. 经常 JOIN 的字段（保证关联键一致）
2. 高基数字段（避免数据倾斜）
3. WHERE 条件高频字段
```

### 分布方式

| 分布方式 | 适用场景 | 说明 |
|----------|----------|------|
| HASH | 绝大多数场景 | 默认使用哈希分布 |
| REPLICATION | 小维度表 | 可选，数据复制到所有节点 |

### 分布键选择示例

```sql
-- ✅ 正确: 使用高基数的关联字段
DISTRIBUTE BY HASH(user_id)

-- ✅ 正确: 多表 JOIN 时使用相同的分布键
-- 表A: DISTRIBUTE BY HASH(order_id)
-- 表B: DISTRIBUTE BY HASH(order_id)

-- ❌ 错误: 低基数字段导致数据倾斜
DISTRIBUTE BY HASH(status)
```

### 检查数据倾斜

```sql
-- 检查分布是否均匀
SELECT 
    table_skewness('table_name', 'distribute_key');
    
-- 如果倾斜度超过 10%，需要重新选择分布键
```

---

## 2. 分区策略

### 默认规则

| 场景 | 分区策略 |
|------|----------|
| 默认 | **不分区** |
| 有会计期需求 | 按 `account_period` 或 `period_code` 分区 |

### 会计期分区示例

```sql
-- 仅当用户有会计期需求时使用
PARTITION BY LIST(account_period) (
    PARTITION p202401 VALUES ('202401'),
    PARTITION p202402 VALUES ('202402'),
    ...
);

-- 或按范围
PARTITION BY RANGE(account_period) (
    PARTITION p202401 VALUES LESS THAN('202402'),
    PARTITION p202402 VALUES LESS THAN('202403'),
    ...
);
```

---

## 3. 存储格式

### 标准配置

| 属性 | 标准值 |
|------|--------|
| 存储格式 | 列存 (COLUMN) |
| 压缩级别 | LOW |

### 设置方式

```sql
-- 标准配置
CREATE TABLE IF NOT EXISTS table_name (...)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(distribute_key)
TO GROUP "LC_DW1";  -- 实时区(schema含drt)使用 TO GROUP "gtoup_version1"
```

---

## 4. 压缩级别

### DWS 压缩级别说明

| 压缩级别 | 说明 | 适用场景 |
|----------|------|----------|
| LOW | 低压缩，读写性能好 | **默认使用** |
| MIDDLE | 中等压缩 | 特殊场景 |
| HIGH | 高压缩，存储最优 | 冷数据归档 |

### 推荐配置

```sql
-- 所有表统一使用 LOW 压缩
WITH (ORIENTATION = COLUMN, COMPRESSION = LOW)
```

---

## 5. 查询优化

### 常见优化技巧

```sql
-- 1. 使用 EXPLAIN 分析执行计划
EXPLAIN ANALYZE SELECT ...;

-- 2. 避免 SELECT *
SELECT col1, col2 FROM t;

-- 3. 避免在 WHERE 中使用函数
WHERE dt >= '2025-01-01'       -- ✅
WHERE DATE(dt) >= '2025-01-01' -- ❌

-- 4. 大表 JOIN 使用相同分布键
-- 确保两表的分布键一致
```

### JOIN 优化

```sql
-- 多表 JOIN: 确保分布键一致
-- 表A: DISTRIBUTE BY HASH(order_id)
-- 表B: DISTRIBUTE BY HASH(order_id)
```

---

## 6. 数据加载

### 批量加载

```sql
-- 使用 INSERT 批量插入
INSERT INTO target_table
SELECT * FROM source_table;
```

### 增量加载

```sql
-- MERGE 语法 (UPSERT)
MERGE INTO target t
USING source s ON t.id = s.id
WHEN MATCHED THEN UPDATE SET t.col = s.col
WHEN NOT MATCHED THEN INSERT VALUES(s.*);
```

---

## 7. 监控与调优

### 常用监控 SQL

```sql
-- 查看表大小
SELECT pg_size_pretty(pg_total_relation_size('table_name'));

-- 查看表统计信息
SELECT * FROM pg_stats WHERE tablename = 'table_name';

-- 更新统计信息
ANALYZE table_name;
```
