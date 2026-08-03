/* R0001: 订单汇总（从订单明细接入表按订单+客户维度聚合 amount，收敛到订单粒度产出目标 F 表） */
SELECT
    a.order_id AS order_id,
    a.cust_id AS cust_id,
    COALESCE(SUM(a.amount), 0) AS total_amount,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_trade_order_di a
GROUP BY a.order_id, a.cust_id;
