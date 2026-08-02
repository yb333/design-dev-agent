/* =====================================================
   R0001: 交易宽表全量装配
   设计意图: 5表JOIN宽表，复杂度未达分段阈值，
             pay/log 收敛用 CTE 内联处理，
             商品维取最新有效行，单条 SELECT 直产目标 F 表
   粒度: 一行=一个订单（输入输出无变化）
   目标表: dws.dwb_trade_wide_f
   ===================================================== */

WITH
/* CTE 1: pay_agg - 支付明细按 order_id 收敛（一个订单可有多笔支付，GROUP BY 收敛到每订单一行） */
pay_agg AS (
    SELECT
        "订单ID" AS order_id,
        COALESCE(SUM("支付金额"), 0) AS total_pay_amt
    FROM ods.ods_payment_di
    WHERE COALESCE(del_flag, 'N') = 'N'
    GROUP BY "订单ID"
),

/* CTE 2: log_agg - 物流明细按 order_id 收敛（一个订单可有多条物流，GROUP BY 收敛到每订单一行） */
log_agg AS (
    SELECT
        "订单ID" AS order_id,
        COALESCE(SUM("运费"), 0) AS total_ship_fee
    FROM ods.ods_logistics_di
    WHERE COALESCE(del_flag, 'N') = 'N'
    GROUP BY "订单ID"
),

/* CTE 3: prod_latest - 商品维取最新有效行（消除多版本历史行，ROW_NUMBER 按 product_id 取最新） */
prod_latest AS (
    SELECT
        "商品ID" AS product_id,
        "商品名称" AS product_name,
        "商品分类" AS category_code,
        ROW_NUMBER() OVER (
            PARTITION BY "商品ID"
            ORDER BY dw_last_update_date DESC NULLS LAST
        ) AS _rn
    FROM dwrdim.dim_product_d
    WHERE COALESCE(del_flag, 'N') = 'N'
)

/* 主查询: 5 表 JOIN 组装宽表（粒度=订单，无变化；LEFT JOIN 右侧字段 COALESCE 兜底） */
SELECT
    o."订单ID" AS order_id,
    o."客户ID" AS cust_id,
    o."商品ID" AS product_id,
    o."订单金额" AS order_amt,
    o."订单数量" AS order_qty,
    COALESCE(c."客户名称", '') AS cust_name,
    COALESCE(c."客户等级", '') AS cust_level,
    COALESCE(pl.product_name, '') AS product_name,
    COALESCE(pl.category_code, '') AS category_code,
    COALESCE(pay.total_pay_amt, 0) AS total_pay_amt,
    COALESCE(log.total_ship_fee, 0) AS total_ship_fee,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_trade_order_di o
LEFT JOIN dwrdim.dim_cust_d c
    ON o."客户ID" = c."客户ID"
    AND COALESCE(c.del_flag, 'N') = 'N'
LEFT JOIN prod_latest pl
    ON o."商品ID" = pl.product_id
    AND pl._rn = 1
LEFT JOIN pay_agg pay
    ON o."订单ID" = pay.order_id
LEFT JOIN log_agg log
    ON o."订单ID" = log.order_id
WHERE COALESCE(o.del_flag, 'N') = 'N';
