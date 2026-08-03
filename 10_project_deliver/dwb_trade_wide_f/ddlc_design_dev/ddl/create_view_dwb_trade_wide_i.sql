/* I视图: dws.dwb_trade_wide_i（交易宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW dws.dwb_trade_wide_i AS
SELECT
    order_id,
    cust_id,
    product_id,
    order_amt,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM dws.dwb_trade_wide_f;

COMMENT ON TABLE dws.dwb_trade_wide_i IS '交易宽表（视图）';

COMMENT ON COLUMN dws.dwb_trade_wide_i.order_id IS '订单ID';
COMMENT ON COLUMN dws.dwb_trade_wide_i.cust_id IS '客户ID';
COMMENT ON COLUMN dws.dwb_trade_wide_i.product_id IS '商品ID';
COMMENT ON COLUMN dws.dwb_trade_wide_i.order_amt IS '订单金额';
COMMENT ON COLUMN dws.dwb_trade_wide_i.del_flag IS '删除标识';
COMMENT ON COLUMN dws.dwb_trade_wide_i.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN dws.dwb_trade_wide_i.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN dws.dwb_trade_wide_i.dw_last_update_date IS '更新时间';
