/* R0001: 订单销售汇总（从订单商品明细表按商品ID聚合销售指标，产出中间表供主规则关联） */
SELECT
    dod.product_id AS product_id,
    COALESCE(SUM(dod.qty), 0) AS total_sales_qty,
    COALESCE(SUM(dod.real_price * dod.qty), 0) AS total_sales_amount,
    COUNT(DISTINCT dod.user_id) AS buyer_cnt,
    COALESCE(SUM(CASE WHEN dod.order_time >= CURRENT_DATE - INTERVAL '30 day' THEN dod.qty ELSE 0 END), 0) AS sales_qty_30d,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_detail_f dod
WHERE COALESCE(dod.del_flag, 'N') = 'N'
GROUP BY dod.product_id;
