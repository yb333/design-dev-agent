/* =====================================================
   表名: dws.dwb_trade_order_d
   规则: R0001 - 订单汇总主加工
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 单源表 ods_trade_order_di 按 订单ID(order_id)+客户ID(cust_id) 分组聚合， 对金额求和(SUM)，收敛到"一行=一个订单+客户组合"的目标粒度，直产目标 F 表。 单表无 JOIN、仅 1 个聚合字段，复杂度低，无需分段建中间表。

   ===================================================== */

CREATE TABLE IF NOT EXISTS dws.dwb_trade_order_d (
    order_id            VARCHAR(64),  /* 订单ID */
    cust_id             VARCHAR(64),  /* 客户ID */
    total_amount        DECIMAL(18,2),  /* 订单总额 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次 */
    last_upd_cycle_id   BIGINT,  /* 更新批次 */
    dw_last_update_date TIMESTAMP(0),  /* 更新时间 */
    /* 审计字段 */
    del_flag            NVARCHAR(1),
    crt_cycle_id        BIGINT,
    last_upd_cycle_id   BIGINT,
    dw_last_update_date TIMESTAMP(0)
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
COMMENT ON COLUMN dws.dwb_trade_order_d.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN dws.dwb_trade_order_d.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN dws.dwb_trade_order_d.dw_last_update_date IS '更新时间';
COMMENT ON COLUMN dws.dwb_trade_order_d.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN dws.dwb_trade_order_d.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN dws.dwb_trade_order_d.dw_last_update_date IS '数仓最后更新时间';
