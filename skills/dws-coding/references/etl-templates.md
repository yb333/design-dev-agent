# ETL 模板

## 1. 简单映射 ETL

适用于单表直取、少量关联的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: {source_tables}
   执行频率: 全量/日增量
   ===================================================== */

INSERT INTO {schema}.{table_name} (
    {target_columns},
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    {source_columns},
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM {source_table}
WHERE {filter_conditions};
```

---

## 2. 多表关联 ETL

适用于需要 JOIN 多张表的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: 
     - {source_table1} ({desc1})
     - {source_table2} ({desc2})
     - {source_table3} ({desc3})
   执行频率: 全量/日增量
   ===================================================== */

INSERT INTO {schema}.{table_name} (
    {target_columns},
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    t1.{col1},
    t1.{col2},
    t2.{col3},
    t3.{col4},
    CASE t1.status
        WHEN 'A' THEN '状态A'
        WHEN 'B' THEN '状态B'
        ELSE '其他'
    END AS status_name,
    COALESCE(t2.amt, 0) AS amt,
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM {source_table1} t1
LEFT JOIN {source_table2} t2 ON t1.id = t2.id AND t2.del_flag = 'N'
LEFT JOIN {source_table3} t3 ON t1.type = t3.type_code
WHERE t1.del_flag = 'N';
```

---

## 3. 聚合中间表 ETL

适用于预聚合统计的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}_step{step}
   来源表: {source_table}
   说明: 按 {group_key} 聚合计算 {metrics}
   ===================================================== */

INSERT INTO {schema}.{table_name}_step{step} (
    {group_key},
    {metric_columns},
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    {group_key},
    COUNT(1) AS cnt,
    COALESCE(SUM(amt), 0) AS total_amt,
    COALESCE(AVG(amt), 0) AS avg_amt,
    MIN(create_time) AS first_time,
    MAX(create_time) AS last_time,
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM {source_table}
WHERE {filter_conditions}
GROUP BY {group_key};
```

---

## 4. RFM 分层 ETL

适用于用户 RFM 分层场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}_step{step}
   来源表: {source_table}
   说明: 计算用户 RFM 分层
   ===================================================== */

INSERT INTO {schema}.{table_name}_step{step} (
    user_id,
    first_order_time,
    last_order_time,
    order_cnt,
    total_amt,
    r_score,
    f_score,
    m_score,
    rfm_segment,
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
WITH user_stat AS (
    SELECT 
        user_id,
        MIN(create_time) AS first_order_time,
        MAX(create_time) AS last_order_time,
        COUNT(*) AS order_cnt,
        COALESCE(SUM(pay_amt), 0) AS total_amt
    FROM {source_table}
    WHERE order_status NOT IN ('CANCELLED', 'DELETED')
    GROUP BY user_id
),
rfm_calc AS (
    SELECT 
        user_id,
        first_order_time,
        last_order_time,
        order_cnt,
        total_amt,
        /* R值: 最近购买时间 */
        CASE 
            WHEN DATEDIFF(CURDATE(), last_order_time) <= 30 THEN 5
            WHEN DATEDIFF(CURDATE(), last_order_time) <= 90 THEN 4
            WHEN DATEDIFF(CURDATE(), last_order_time) <= 180 THEN 3
            WHEN DATEDIFF(CURDATE(), last_order_time) <= 365 THEN 2
            ELSE 1
        END AS r_score,
        /* F值: 购买频率 */
        CASE 
            WHEN order_cnt >= 20 THEN 5
            WHEN order_cnt >= 10 THEN 4
            WHEN order_cnt >= 5 THEN 3
            WHEN order_cnt >= 2 THEN 2
            ELSE 1
        END AS f_score,
        /* M值: 消费金额 */
        CASE 
            WHEN total_amt >= 10000 THEN 5
            WHEN total_amt >= 5000 THEN 4
            WHEN total_amt >= 1000 THEN 3
            WHEN total_amt >= 100 THEN 2
            ELSE 1
        END AS m_score
    FROM user_stat
)
SELECT 
    user_id,
    first_order_time,
    last_order_time,
    order_cnt,
    total_amt,
    r_score,
    f_score,
    m_score,
    /* RFM 分层 */
    CASE 
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '重要价值客户'
        WHEN r_score >= 4 AND f_score < 4 AND m_score >= 4 THEN '重要发展客户'
        WHEN r_score < 4 AND f_score >= 4 AND m_score >= 4 THEN '重要保持客户'
        WHEN r_score >= 4 AND f_score < 4 AND m_score < 4 THEN '一般发展客户'
        WHEN r_score < 4 AND f_score >= 4 AND m_score < 4 THEN '一般保持客户'
        WHEN r_score < 4 AND f_score < 4 AND m_score >= 4 THEN '重要挽留客户'
        ELSE '一般客户'
    END AS rfm_segment,
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM rfm_calc;
```

---

## 5. 取最新/第一条记录 ETL

适用于一对多关系取最新记录的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}_step{step}
   来源表: {source_table}
   说明: 按 {group_key} 取最新记录
   ===================================================== */

INSERT INTO {schema}.{table_name}_step{step} (
    {group_key},
    {columns},
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    {group_key},
    {columns},
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM (
    SELECT 
        {group_key},
        {columns},
        ROW_NUMBER() OVER (PARTITION BY {group_key} ORDER BY {order_column} DESC) AS rn
    FROM {source_table}
    WHERE {filter_conditions}
) t
WHERE rn = 1;
```

---

## 6. 数据脱敏 ETL

适用于包含敏感信息的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: {source_table}
   说明: 包含数据脱敏处理
   ===================================================== */

INSERT INTO {schema}.{table_name} (
    user_id,
    user_name,
    phone_masked,
    email_masked,
    id_card_masked,
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    user_id,
    user_name,
    /* 手机号脱敏: 保留前3后4 */
    CONCAT(LEFT(phone, 3), '****', RIGHT(phone, 4)) AS phone_masked,
    /* 邮箱脱敏: 保留前2和域名 */
    CONCAT(LEFT(email, 2), '***@', SUBSTRING_INDEX(email, '@', -1)) AS email_masked,
    /* 身份证脱敏: 保留前4后4 */
    CONCAT(LEFT(id_card, 4), '**********', RIGHT(id_card, 4)) AS id_card_masked,
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM {source_table}
WHERE del_flag = 'N';
```

---

## 7. 宽表组装 ETL

适用于多表关联组装宽表的场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number} (最终步骤)
   目标表: {schema}.{table_name}
   来源表: {source_tables}
   中间表: {intermediate_tables}
   说明: 组装最终宽表
   ===================================================== */

INSERT INTO {schema}.{table_name} (
    /* 主表字段 */
    {main_columns},
    /* 维度字段 */
    {dimension_columns},
    /* 统计字段 (来自中间表) */
    {stat_columns},
    /* 审计字段 */
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    /* 主表字段 */
    t.{col1},
    t.{col2},
    
    /* 维度字段 (关联获取) */
    u.user_name,
    d.dept_name,
    CASE t.status
        WHEN 'A' THEN '状态A'
        WHEN 'B' THEN '状态B'
        ELSE '其他'
    END AS status_name,
    
    /* 统计字段 (来自中间表) */
    COALESCE(s.cnt, 0) AS stat_cnt,
    COALESCE(s.amt, 0) AS stat_amt,
    
    /* 审计字段 */
    'N',                                          /* del_flag */
'${P_CYCLE_ID}',                             /* crt_cycle_id */
'${P_CYCLE_ID}',                             /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM {main_table} t

/* 关联维度表 */
LEFT JOIN dim_user_f u ON t.user_id = u.user_id
LEFT JOIN dim_dept_f d ON t.dept_id = d.dept_id

/* 关联中间表 (预计算的统计) */
LEFT JOIN {table_name}_step1 s ON t.{key} = s.{key}

WHERE t.del_flag = 'N';
```

---

## 8. MERGE (UPSERT) ETL

适用于增量更新场景。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: {source_table}
   说明: 增量更新 (MERGE)
   ===================================================== */

MERGE INTO {schema}.{table_name} t
USING (
    SELECT 
        {columns},
        CURRENT_TIMESTAMP AS update_time
    FROM {source_table}
    WHERE {incremental_condition}
) s
ON t.{pk_column} = s.{pk_column}
WHEN MATCHED THEN
    UPDATE SET
        {column1} = s.{column1},
        {column2} = s.{column2},
        update_time = s.update_time
WHEN NOT MATCHED THEN
    INSERT ({columns}, del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date)
    VALUES (s.{columns}, 'N', '${P_CYCLE_ID}', '${P_CYCLE_ID}', CURRENT_TIMESTAMP);
```

---

## 9. 粒度对齐后关联 ETL

适用于粒度变化（聚合/行转列/去重）后需要关联其他表的场景。确保被关联表粒度与主表一致，避免数据膨胀。

```sql
/* =====================================================
   ETL 转换脚本
   步骤: {step_number}
   目标表: {schema}.{table_name}
   来源表: {source_tables}
   说明: 粒度对齐后关联（参照设计文档关联安全分析）
   ===================================================== */

/* CTE 1: 粒度变化操作（聚合/行转列/去重） */
WITH grain_changed AS (
    SELECT 
        {main_key},
        {aggregate_columns}
    FROM {source_table}
    WHERE del_flag = 'N'
    GROUP BY {main_key}
),

/* CTE 2: 被关联表粒度对齐（收敛到与主表相同粒度） */
/* ⚠️ 仅在被关联表粒度更细时需要此步骤 */
aligned_dim AS (
    SELECT 
        {join_key},
        {aggregate_or_latest_columns}
    FROM {related_table}
    WHERE del_flag = 'N'
      AND {filter_conditions}
    GROUP BY {join_key}
)

/* 主查询: 安全 JOIN（粒度一致后关联） */
INSERT INTO {schema}.{table_name} (
    {target_columns},
    del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date
)
SELECT 
    gc.{main_key},
    gc.{aggregate_columns},
    ad.{related_columns},
    'N',                                          /* del_flag */
    '${P_CYCLE_ID}',                              /* crt_cycle_id */
    '${P_CYCLE_ID}',                              /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM grain_changed gc
LEFT JOIN aligned_dim ad ON gc.{join_key} = ad.{join_key}
{additional_joins};
```

**使用场景对照**:

| 关联安全分析中的对齐策略 | CTE 实现方式 |
|--------------------------|-------------|
| 直接关联，无需对齐 | 不需要 aligned_dim CTE，直接 LEFT JOIN |
| 先 GROUP BY 收敛再关联 | aligned_dim 使用 GROUP BY 聚合到主表粒度 |
| 先 ROW_NUMBER 取最新再关联 | aligned_dim 使用 ROW_NUMBER 去重后取第一条 |

> ⚠️ 粒度对齐的具体方式必须与设计文档「关联安全分析」表中的「对齐策略」一致。
