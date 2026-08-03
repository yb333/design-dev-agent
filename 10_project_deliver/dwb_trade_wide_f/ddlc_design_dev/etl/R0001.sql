/* R0001: 交易宽表全量装配（单源表无JOIN，字段全部直接复制或固定赋值，无粒度变化，单条INSERT直产目标F表） */
SELECT
    -- order_id: 直取 o.order_id
    o.order_id AS order_id,
    -- cust_id: 直取 o.cust_id
    o.cust_id AS cust_id,
    -- product_id: 直取 o.product_id
    o.product_id AS product_id,
    -- order_amt: 直取 o.order_amt，金额字段按规范兜底 0
    COALESCE(o.order_amt, 0) AS order_amt,
    -- del_flag: 固定赋值
    'N' AS del_flag,
    -- crt_cycle_id: 固定赋值（审计批次占位符）
    '${P_CYCLE_ID}' AS crt_cycle_id,
    -- last_upd_cycle_id: 固定赋值（审计批次占位符）
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    -- dw_last_update_date: 固定赋值
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_trade_order_di o;
