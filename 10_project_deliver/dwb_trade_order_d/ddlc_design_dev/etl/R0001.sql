/* R0001: 订单汇总聚合（从订单明细接入表按 order_id+cust_id 聚合到订单粒度，汇总金额，直取订单与客户标识，补审计字段） */
SELECT
    a.order_id AS order_id,
    a.cust_id AS cust_id,
    /* 订单总额：对同一 order_id + cust_id 的 amount 求和汇总 */
    COALESCE(SUM(a.amount), 0) AS total_amount,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_trade_order_di a
WHERE a.del_flag = 'N'
GROUP BY a.order_id, a.cust_id;
