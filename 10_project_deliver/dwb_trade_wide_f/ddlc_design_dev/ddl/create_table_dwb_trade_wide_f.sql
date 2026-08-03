/* =====================================================
   表名: dws.dwb_trade_wide_f
   规则: R0001 - 交易宽表全量装配
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 单源表无JOIN，字段全部直接复制或固定赋值，无粒度变化，单条INSERT直产目标F表
   ===================================================== */

CREATE TABLE IF NOT EXISTS dws.dwb_trade_wide_f (
    order_id            VARCHAR(64),  /* 订单ID */
    cust_id             VARCHAR(64),  /* 客户ID */
    product_id          VARCHAR(64),  /* 商品ID */
    order_amt           DECIMAL(18,2),  /* 订单金额 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次 */
    last_upd_cycle_id   BIGINT,  /* 更新批次 */
    dw_last_update_date TIMESTAMP(0)  /* 更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE dws.dwb_trade_wide_f IS '交易宽表';

COMMENT ON COLUMN dws.dwb_trade_wide_f.order_id IS '订单ID';
COMMENT ON COLUMN dws.dwb_trade_wide_f.cust_id IS '客户ID';
COMMENT ON COLUMN dws.dwb_trade_wide_f.product_id IS '商品ID';
COMMENT ON COLUMN dws.dwb_trade_wide_f.order_amt IS '订单金额';
COMMENT ON COLUMN dws.dwb_trade_wide_f.del_flag IS '删除标识';
COMMENT ON COLUMN dws.dwb_trade_wide_f.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN dws.dwb_trade_wide_f.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN dws.dwb_trade_wide_f.dw_last_update_date IS '更新时间';
