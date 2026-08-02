/* R0001: 订单汇总主加工
   单源表 ods.ods_trade_order_di 按 订单ID(order_id)+客户ID(cust_id) 分组聚合，
   对金额求和(SUM)，收敛到"一行=一个订单+客户组合"的目标粒度。
   单表无 JOIN、仅 1 个聚合字段。 */
SELECT
    a."订单ID"                                   AS order_id,
    a."客户ID"                                   AS cust_id,
    COALESCE(SUM(a."金额"), 0)                   AS total_amount,
    /* 审计字段 */
    'N'                                          AS del_flag,
    '${P_CYCLE_ID}'                              AS crt_cycle_id,
    '${P_CYCLE_ID}'                              AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                            AS dw_last_update_date
FROM ods.ods_trade_order_di a
GROUP BY
    a."订单ID",
    a."客户ID";
