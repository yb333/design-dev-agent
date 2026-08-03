/* =====================================================
   表名: dws.dwb_trade_order_d
   规则: R0001 - 订单汇总
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 从订单明细接入表按订单+客户维度聚合 amount，收敛到订单粒度产出目标 F 表
   ===================================================== */

CREATE TABLE IF NOT EXISTS dws.dwb_trade_order_d (
    order_id            VARCHAR(64),  /* 订单ID */
    cust_id             VARCHAR(64),  /* 客户ID */
    total_amount        DECIMAL(18,2),  /* 订单总额 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE dws.dwb_trade_order_d IS '订单汇总表';

COMMENT ON COLUMN dws.dwb_trade_order_d.order_id IS '订单ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.cust_id IS '客户ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.total_amount IS '订单总额';
COMMENT ON COLUMN dws.dwb_trade_order_d.del_flag IS '删除标识';
COMMENT ON COLUMN dws.dwb_trade_order_d.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.dw_last_update_date IS '数仓最后更新时间';
