# SELECT 模板

> coder 的唯一产出是 SELECT 语句。INSERT 由 run_ut.py 按平台规则包装，DDL 由 assemble_ddl.py 生成。
> 本文件提供各种加工模式的 SELECT 模板。审计字段（4个）直接在 SELECT 里带上。

---

## 1. 简单映射 SELECT

适用于单表直取、少量关联的场景。

```sql
/* R0001: {rule_name}（{design_intent}） */
SELECT
    t.contract_no AS contract_no,
    t.contract_id AS contract_id,
    COALESCE(t.amount, 0) AS amount,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{source_table} t
WHERE t.del_flag = 'N';
```

---

## 2. 多表关联 SELECT

适用于需要 JOIN 多张表的场景。

```sql
/* R0001: {rule_name}（{design_intent}） */
SELECT
    t1.contract_no AS contract_no,
    t1.contract_id AS contract_id,
    t2.dept_name AS dept_name,
    CASE t1.status
        WHEN 'A' THEN '状态A'
        WHEN 'B' THEN '状态B'
        ELSE '其他'
    END AS status_name,
    COALESCE(t2.amount, 0) AS amount,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{source_table1} t1
LEFT JOIN {schema}.{source_table2} t2 ON t1.id = t2.id AND t2.del_flag = 'N'
LEFT JOIN {schema}.{source_table3} t3 ON t1.type = t3.type_code
WHERE t1.del_flag = 'N';
```

---

## 3. 聚合 SELECT

适用于预聚合统计的场景。注意 GROUP BY 必须包含所有非聚合字段。

```sql
/* R0001: {rule_name}（{design_intent}） */
SELECT
    t.contract_id AS contract_id,
    t.pu_id AS pu_id,
    COUNT(1) AS cnt,
    COALESCE(SUM(t.amount), 0) AS total_amt,
    COALESCE(AVG(t.amount), 0) AS avg_amt,
    MIN(t.create_time) AS first_time,
    MAX(t.create_time) AS last_time,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{source_table} t
WHERE t.del_flag = 'N'
GROUP BY t.contract_id, t.pu_id;
```

---

## 4. 行转列 SELECT（pivot）

适用于将行数据转为列的场景。典型：报表指标行转列。

```sql
/* R0001: {rule_name}（{design_intent}） */
SELECT
    t.contract_id AS contract_id,
    t.pu_id AS pu_id,
    SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_usd ELSE 0 END) AS equip_org_amt_usd,
    SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_rmb ELSE 0 END) AS equip_org_amt_rmb,
    SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_usd ELSE 0 END) AS equip_cfm_amt_usd,
    SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_rmb ELSE 0 END) AS equip_cfm_amt_rmb,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{source_table} t
WHERE t.del_flag = 'N'
GROUP BY t.contract_id, t.pu_id;
```

---

## 5. 取最新有效行 SELECT

适用于一对多关系取最新记录的场景（关联安全策略：维度表取最新有效行）。

```sql
/* R0001: {rule_name}（{design_intent}） */
SELECT
    t.contract_id AS contract_id,
    pu.pu_name AS pu_name,
    pu.pu_key AS pu_key,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{main_table} t
LEFT JOIN (
    SELECT
        pu_id,
        pu_name,
        pu_key,
        ROW_NUMBER() OVER (PARTITION BY pu_id ORDER BY update_time DESC) AS rn
    FROM {schema}.{dim_table}
    WHERE del_flag = 'N'
) pu ON t.pu_id = pu.pu_id AND pu.rn = 1
WHERE t.del_flag = 'N';
```

---

## 6. 粒度对齐后关联 SELECT（CTE 模式）

适用于粒度变化（聚合/行转列/去重）后需要关联其他表的场景。
确保被关联表粒度与主表一致，避免数据膨胀（关联安全）。

```sql
/* R0001: {rule_name}（{design_intent}） */
/* CTE 1: 被关联表收敛到主表粒度（排除非洲发票 + 按合同+pu汇总） */
WITH inv_agg AS (
    SELECT
        contract_id,
        pu_id,
        COALESCE(SUM(inv_inst_amt_usd), 0) AS inv_tol_amt_usd,
        COALESCE(SUM(inv_inst_amt_rmb), 0) AS inv_tol_amt_rmb
    FROM {schema}.{source_table}
    WHERE del_flag = 'N'
      AND region != 'AFRICA'  /* 排除非洲发票 */
    GROUP BY contract_id, pu_id
)

/* 主查询: 安全 JOIN（粒度一致后关联） */
SELECT
    t.contract_no AS contract_no,
    t.contract_id AS contract_id,
    t.pu_id AS pu_id,
    COALESCE(inv_agg.inv_tol_amt_usd, 0) AS inv_tol_amt_usd,
    COALESCE(inv_agg.inv_tol_amt_rmb, 0) AS inv_tol_amt_rmb,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{main_table} t
LEFT JOIN inv_agg ON t.contract_id = inv_agg.contract_id AND t.pu_id = inv_agg.pu_id
WHERE t.del_flag = 'N';
```

**关联安全策略对照**:

| 关联安全分析中的对齐策略 | CTE 实现方式 |
|--------------------------|-------------|
| 直接关联，无需对齐 | 不需要 CTE，直接 LEFT JOIN |
| 先 GROUP BY 收敛再关联 | CTE 里 GROUP BY 聚合到主表粒度 |
| 先 ROW_NUMBER 取最新再关联 | CTE 里 ROW_NUMBER 去重后取 rn=1 |
| 先排除再聚合 | CTE 里 WHERE 过滤后 GROUP BY |

> ⚠️ 粒度对齐的具体方式必须与切片 join_safety 里的 strategy 一致。

---

## 7. 宽表组装 SELECT（多 CTE）

适用于多源多步骤加工组装宽表的场景。每个 CTE 处理一个数据源，最后组装。

```sql
/* R0001: {rule_name}（{design_intent}） */
WITH
/* CTE 1: 主表行转列收敛 */
main_pivot AS (
    SELECT
        contract_id,
        pu_id,
        SUM(CASE WHEN rpt_code = 'fbt_0001' THEN rpt_value_usd ELSE 0 END) AS equip_org_amt_usd,
        SUM(CASE WHEN rpt_code = 'fbt_0002' THEN rpt_value_usd ELSE 0 END) AS equip_cfm_amt_usd
    FROM {schema}.{main_table}
    WHERE del_flag = 'N'
    GROUP BY contract_id, pu_id
),
/* CTE 2: 发票收敛（排除非洲） */
inv_agg AS (
    SELECT
        contract_id,
        pu_id,
        COALESCE(SUM(inv_inst_amt_usd), 0) AS inv_tol_amt_usd
    FROM {schema}.{inv_table}
    WHERE del_flag = 'N' AND region != 'AFRICA'
    GROUP BY contract_id, pu_id
),
/* CTE 3: 维表取最新有效行 */
pu_latest AS (
    SELECT
        pu_id,
        pu_key,
        ROW_NUMBER() OVER (PARTITION BY pu_id ORDER BY update_time DESC) AS rn
    FROM {schema}.{dim_table}
    WHERE del_flag = 'N'
)

/* 最终组装 */
SELECT
    t.contract_no AS contract_no,
    t.contract_id AS contract_id,
    t.pu_id AS pu_id,
    mp.equip_org_amt_usd AS equip_org_amt_usd,
    mp.equip_cfm_amt_usd AS equip_cfm_amt_usd,
    COALESCE(ia.inv_tol_amt_usd, 0) AS inv_tol_amt_usd,
    pl.pu_key AS pu_key,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM {schema}.{main_table} t
LEFT JOIN main_pivot mp ON t.contract_id = mp.contract_id AND t.pu_id = mp.pu_id
LEFT JOIN inv_agg ia ON t.contract_id = ia.contract_id AND t.pu_id = ia.pu_id
LEFT JOIN pu_latest pl ON t.pu_id = pl.pu_id AND pl.rn = 1
WHERE t.del_flag = 'N';
```

---

## 编码要点

### 审计字段（每个 SELECT 必须带上）

```sql
'N' AS del_flag,
'${P_CYCLE_ID}' AS crt_cycle_id,
'${P_CYCLE_ID}' AS last_upd_cycle_id,
CURRENT_TIMESTAMP AS dw_last_update_date
```

> 如果 del_flag 有自定义逻辑（来自 mapping 的映射表达式），用 mapping 的逻辑替代 'N'。

### NULL 处理

**该不该 COALESCE 是业务语义判断，不是铁律**——业务要 NULL 时（可选字段没值）保留 NULL 才对。需要默认值时：
```sql
/* 金额类：NULL 在业务里等于 0 */
COALESCE(t.amount, 0) AS amount
/* LEFT JOIN 结果按业务：要默认值就 COALESCE，要保留关联失败信号就不加 */
COALESCE(inv_agg.total, 0) AS total
```
> 主键/外键不要 COALESCE（NULL→0 会掩盖关联失败）；可选字段保留 NULL。详见 coding-standards §1.3。

### 字段别名

每个输出字段必须用 `AS` 显式命名，且和切片的 target_field 一致：
```sql
/* ✅ 明确别名 */
t.contract_no AS contract_no
/* ❌ 隐式，check_sql 检查不到 */
t.contract_no
```

### 不能 SELECT *

```sql
/* ✅ 列出字段 */
SELECT t.contract_no, t.amount
/* ❌ 禁止 */
SELECT t.*
```

> 注释一律用 `/* */` 块注释，禁止 `--` 行注释（详见编码规范 §7）。

## 8. 增量取数 SELECT（step_type=incremental_extract）

从源表按增量范围取数到临时表。**WHERE 必须加增量过滤条件**（从切片 incremental.filter 取）：

```sql
/* R0001: 订单增量取数（按 update_time 取增量到 tmp_order） */
SELECT
    t.order_id AS order_id,
    t.cust_id AS cust_id,
    t.order_amt AS order_amt,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_order_f t
WHERE t.update_time >= '${BIZ_DATE_START}' AND t.update_time < '${BIZ_DATE_END}'
;
```

要点：
- WHERE 的增量条件从切片的 `incremental.filter` 取（如 `update_time >= '${BIZ_DATE_START}'`）
- 分区增量用分区字段过滤（如 `dt >= '${BIZ_DATE_START}'`）
- 只写增量版，初始化版由脚本自动生成（filter 换 init_filter）

## 9. 读中间表合并 SELECT（step_type=merge）

读临时表（tmp_a/tmp_b）产出合并结果集。**写入动作（MERGE）由平台配置，这里只写 SELECT**：

```sql
/* R0003: 合并订单+支付增量到目标宽表（读 tmp_order/tmp_payment） */
SELECT
    o.order_id AS order_id,
    o.cust_id AS cust_id,
    o.order_amt AS order_amt,
    COALESCE(p.pay_amt, 0) AS pay_amt,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM slord.tmp_order o
LEFT JOIN slord.tmp_payment p
    ON o.order_id = p.order_id
;
```

要点：
- FROM 读的是临时表（tmp_order/tmp_payment），不是源表
- MERGE 的 ON 条件（如 `T.order_id=T1.order_id`）由 designer 填 write_condition，平台/run_ut 配置，不在 SELECT 里
