/* R0001: 交易宽表主表加载（单源主表直加载，无关联无加工，全量覆盖写入目标F表） */
SELECT
    COALESCE(o.order_id, '') AS order_id,
    COALESCE(o.cust_id, '') AS cust_id,
    COALESCE(o.product_id, '') AS product_id,
    COALESCE(o.order_amt, 0) AS order_amt,
    'N' AS del_flag,                          /* 审计字段：删除标识固定 N */
    '${P_CYCLE_ID}' AS crt_cycle_id,          /* 审计字段：创建批次号 */
    '${P_CYCLE_ID}' AS last_upd_cycle_id,     /* 审计字段：最后更新批次号 */
    CURRENT_TIMESTAMP AS dw_last_update_date  /* 审计字段：数仓最后更新时间 */
FROM ods.ods_trade_order_di o
WHERE o.del_flag = 'N';
