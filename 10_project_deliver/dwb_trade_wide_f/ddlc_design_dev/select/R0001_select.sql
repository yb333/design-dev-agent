/* =====================================================
   R0001: 交易宽表全量加工
   design_intent: 以订单明细为主表，LEFT JOIN 客户维、商品维补维度属性，
                  通过 CTE 预聚合支付和物流（按 order_id 汇总收敛多行），
                  一次性产出交易宽表 F 表。
   target: dws.dwb_trade_wide_f（1 订单 1 行，全量调度）
   ===================================================== */

WITH
/* CTE pay_agg: 按 order_id 汇总支付金额，将一个订单的多笔支付收敛为一行，避免 JOIN 后数据发散 */
pay_agg AS (
    SELECT
        order_id,
        COALESCE(SUM(pay_amt), 0) AS total_pay_amt   /* 源字段 pay_amt = ods_payment_di.支付金额（字段名按目标表命名约定） */
    FROM ods.ods_payment_di
    WHERE del_flag = 'N'
    GROUP BY order_id
),

/* CTE log_agg: 按 order_id 汇总运费，将一个订单的多条物流收敛为一行，避免 JOIN 后数据发散 */
log_agg AS (
    SELECT
        order_id,
        COALESCE(SUM(ship_fee), 0) AS total_ship_fee /* 源字段 ship_fee = ods_logistics_di.运费（字段名按目标表命名约定） */
    FROM ods.ods_logistics_di
    WHERE del_flag = 'N'
    GROUP BY order_id
)

SELECT
    o.order_id                                AS order_id,
    o.cust_id                                 AS cust_id,
    o.product_id                              AS product_id,
    COALESCE(o.order_amt, 0)                  AS order_amt,
    COALESCE(o.order_qty, 0)                  AS order_qty,
    COALESCE(c.cust_name, '')                 AS cust_name,
    COALESCE(c.cust_level, '')                AS cust_level,
    COALESCE(p.product_name, '')              AS product_name,
    COALESCE(p.category_code, '')             AS category_code,
    COALESCE(pay_agg.total_pay_amt, 0)        AS total_pay_amt,
    COALESCE(log_agg.total_ship_fee, 0)       AS total_ship_fee,
    'N'                                       AS del_flag,
    '${P_CYCLE_ID}'                           AS crt_cycle_id,
    '${P_CYCLE_ID}'                           AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                         AS dw_last_update_date
FROM ods.ods_trade_order_di o
/* 客户维：join_key_unique=true，直接关联（假设当前有效快照） */
LEFT JOIN dwrdim.dim_cust_d c
    ON o.cust_id = c.cust_id
    AND c.del_flag = 'N'
/* 商品维：拉链表，join_key_unique=false，strategy=取最新有效行
   ⚠️ 假设字段名 is_current（基于 DWS 维度表标准模板 effective_dt/expiry_dt/is_current/version_num），
      切片未给出具体拉链过滤字段名，待 RS 确认；若实际为生效/失效日期区间，
      应替换为 p.effective_dt <= CURRENT_DATE AND p.expiry_dt > CURRENT_DATE */
LEFT JOIN dwrdim.dim_product_d p
    ON o.product_id = p.product_id
    AND p.del_flag = 'N'
    AND p.is_current = 'Y'
/* 支付预聚合：CTE 已收敛到 order_id 粒度，安全关联 */
LEFT JOIN pay_agg
    ON o.order_id = pay_agg.order_id
/* 物流预聚合：CTE 已收敛到 order_id 粒度，安全关联 */
LEFT JOIN log_agg
    ON o.order_id = log_agg.order_id
WHERE o.del_flag = 'N';
