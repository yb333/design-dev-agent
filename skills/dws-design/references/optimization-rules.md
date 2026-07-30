# 优化规则

> **注意**: 分段策略由 Designer SKILL.md 统一管理，本文件不定义分段阈值。
> 分段规则详见 Designer SKILL.md「4. 设计分段」和「5. 中间表设计原则」。

## 1. 分布键优化

### 选择优先级

```
1. JOIN 关联字段 (多表 JOIN 时必须一致)
2. 高基数字段 (避免数据倾斜)
3. WHERE 高频字段 (利用本地过滤)
```

### 倾斜检测

```sql
-- 检查数据分布
SELECT 
    gp_segment_id,
    COUNT(*) as cnt
FROM {table_name}
GROUP BY gp_segment_id
ORDER BY cnt DESC;

-- 如果 max/min > 1.1，存在倾斜
```

### 常见分布键选择

| 表类型 | 推荐分布键 |
|--------|------------|
| 订单事实表 | `order_id` |
| 用户行为表 | `user_id` |
| 交易流水表 | `txn_id` |
| 合同事实表 | `contract_id` |
| 中间表 | 与下游 JOIN 字段一致 |

---

## 2. 分区优化

> **注意**: 默认不分区，仅会计期场景才分区（与主编码规范一致）。

### 粒度选择

```sql
-- 日分区 (数据量 > 1000万/日)
PARTITION BY RANGE(dt) (
    PARTITION p20250101 VALUES LESS THAN('2025-01-02'),
    PARTITION p20250102 VALUES LESS THAN('2025-01-03'),
    ...
);

-- 月分区 (数据量 < 1000万/日)
PARTITION BY RANGE(dt) (
    PARTITION p202501 VALUES LESS THAN('2025-02-01'),
    PARTITION p202502 VALUES LESS THAN('2025-03-01'),
    ...
);
```

### 分区裁剪

```sql
-- ✅ 能利用分区裁剪
WHERE dt >= '2025-01-01' AND dt < '2025-02-01'
WHERE dt = '2025-01-15'
WHERE dt IN ('2025-01-01', '2025-01-02')

-- ❌ 无法利用分区裁剪
WHERE TO_CHAR(dt, 'YYYYMM') = '202501'
WHERE EXTRACT(MONTH FROM dt) = 1
WHERE dt + INTERVAL '1 DAY' = '2025-01-16'
```

---

## 3. JOIN 优化

### 小表广播

```sql
-- 维度表使用 REPLICATION 分布
CREATE TABLE dim_product (...) DISTRIBUTE BY REPLICATION;

-- JOIN 时自动广播
SELECT f.*, d.product_name
FROM fact_order f
JOIN dim_product d ON f.product_id = d.product_id;
```

### 大表 HASH 分布

```sql
-- 两表使用相同分布键
CREATE TABLE fact_a (...) DISTRIBUTE BY HASH(user_id);
CREATE TABLE fact_b (...) DISTRIBUTE BY HASH(user_id);

-- JOIN 时本地关联，无需数据重分布
SELECT a.*, b.*
FROM fact_a a
JOIN fact_b b ON a.user_id = b.user_id;
```

### JOIN 顺序

```sql
-- 小表在前，大表在后
SELECT *
FROM small_dim d        -- 小表
JOIN medium_fact f1 ON d.id = f1.dim_id
JOIN large_fact f2 ON f1.id = f2.fact_id;
```

---

## 4. 聚合优化

### 预聚合

```sql
-- 如果多个下游都需要相同聚合，创建汇总表
CREATE TABLE dws_daily_sales AS
SELECT 
    dt,
    product_id,
    SUM(sales_amt) as sales_amt,
    COUNT(*) as order_cnt
FROM dwd_order
GROUP BY dt, product_id;
```

### 聚合函数选择

```sql
-- ✅ 使用特定聚合函数
COUNT(DISTINCT user_id)
SUM(CASE WHEN status = 'A' THEN 1 ELSE 0 END)

-- ❌ 避免在聚合中使用子查询
SUM((SELECT COUNT(*) FROM t2 WHERE t2.id = t1.id))
```

---

## 5. 存储优化

> **注意**: DWS 统一使用列存 + LOW 压缩（与主编码规范 dws-coding-standards.md 一致）。

| 属性 | 标准值 | 说明 |
|------|--------|------|
| 存储格式 | 列存 (COLUMN) | 默认使用列存 |
| 压缩级别 | LOW | 统一使用 LOW 压缩 |

```sql
-- DWS 标准设置（与主编码规范一致）
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
```

---

## 6. 查询优化

> **注意**: DWS 列存表不支持索引，查询优化依赖分区裁剪和分布键对齐。

### 避免全表扫描

```sql
-- ✅ 利用分区裁剪
SELECT * FROM fact_order
WHERE dt = '2025-01-15';

-- ❌ 全表扫描（没有分区条件）
SELECT * FROM fact_order
WHERE user_id = 12345;
```

### 减少数据量

```sql
-- ✅ 早过滤
SELECT a.*, b.name
FROM (
    SELECT * FROM large_table WHERE dt = '2025-01-15'  -- 先过滤
) a
JOIN dim_table b ON a.id = b.id;

-- ❌ 晚过滤
SELECT *
FROM large_table a
JOIN dim_table b ON a.id = b.id
WHERE a.dt = '2025-01-15';  -- JOIN 后过滤
```

### 使用 CTE 优化复杂查询

```sql
-- 分解复杂查询为多个 CTE
WITH 
step1 AS (
    SELECT * FROM source WHERE status = 'A'
),
step2 AS (
    SELECT id, SUM(amt) as total_amt
    FROM step1
    GROUP BY id
)
SELECT * FROM step2;
```

---

## 7. 数据加载优化

### 批量 vs 单条

```sql
-- ✅ 批量插入
INSERT INTO target
SELECT * FROM source;

-- ❌ 单条插入
INSERT INTO target VALUES (1, 'a');
INSERT INTO target VALUES (2, 'b');
```

### 并行加载

```sql
-- 按分区并行加载
-- Session 1
INSERT INTO target PARTITION(p20250101) SELECT * FROM source WHERE dt = '2025-01-01';

-- Session 2
INSERT INTO target PARTITION(p20250102) SELECT * FROM source WHERE dt = '2025-01-02';
```

---

## 8. 内存优化

### WorkMem 设置

```sql
-- 临时设置会话内存
SET work_mem = '256MB';

-- 复杂排序/聚合操作前设置
SET work_mem = '512MB';
```

### 避免内存溢出

```sql
-- ✅ 分批处理
INSERT INTO target
SELECT * FROM source
WHERE dt BETWEEN '2025-01-01' AND '2025-01-31'
LIMIT 1000000;

-- 使用游标处理大结果集
BEGIN;
DECLARE cur CURSOR FOR SELECT * FROM large_table;
FETCH 1000 FROM cur;
-- 处理...
COMMIT;
```

---

## 9. 性能检查清单

> **注意**: 分段合理性由 Designer SKILL.md 管理，此处不重复检查段数。

### 设计阶段

- [ ] 分布键选择合理（高基数、JOIN 一致）
- [ ] 分区策略适合数据规模（默认不分区）
- [ ] 存储格式正确（列存 COLUMN）
- [ ] 压缩级别正确（LOW）

### 开发阶段

- [ ] 使用 EXPLAIN 验证执行计划
- [ ] 利用分区裁剪
- [ ] JOIN 顺序优化
- [ ] 减少 SELECT *

### 测试阶段

- [ ] 检查数据倾斜
- [ ] 验证分区有效性
- [ ] 性能基准测试
- [ ] 并发测试

---

## 10. 字段分组规则 (避免重复)

### 分组原则

字段必须**只归属于一个分组**，避免重复归类。

### 分组定义

| 分组 | 包含字段 | 数据来源 |
|------|----------|----------|
| 订单基础 | order_id, order_no, order_status, amounts, etc. | 订单事实表 |
| 用户维度 | user_id, user_name, user_profile_fields | 用户维表 + **用户画像中间表** |
| 商品维度 | product_id, product_name, category, brand | 商品维表 + **商品画像中间表** |
| 店铺维度 | shop_id, shop_name, shop_profile | 店铺维表 + **店铺画像中间表** |
| 收货地址 | receiver_name, receiver_address, region | 订单事实表 + 地区维表 |
| 支付信息 | pay_id, pay_method, pay_status | 支付事实表 + 支付方式维表 |
| 物流信息 | logistics_id, logistics_company, warehouse | 物流事实表 + 物流/仓库维表 |
| 营销活动 | coupon_id, activity_id, discount | 优惠券/活动维表 |
| 退款信息 | refund_id, refund_amount, refund_status | 退款事实表 |

### 常见错误

| 错误 | 说明 | 修正 |
|------|------|------|
| `fav_pay_method` 归入支付信息 | 该字段来自用户画像中间表 | 只归入用户维度 |
| `user_coupon_used_cnt` 归入营销活动 | 该字段来自用户画像中间表 | 只归入用户维度 |
| `product_sales_cnt` 归入订单信息 | 该字段来自商品画像中间表 | 只归入商品维度 |

### 判断规则

```
如果字段来自中间表（stg_xxx_profile_agg）:
  → 归入对应的维度分组（用户/商品/店铺）
  
如果字段来自维度表（dim_xxx_f）:
  → 归入对应的维度分组
  
如果字段来自事实表（dwd_xxx_f）:
  → 按业务含义归入对应分组
```
