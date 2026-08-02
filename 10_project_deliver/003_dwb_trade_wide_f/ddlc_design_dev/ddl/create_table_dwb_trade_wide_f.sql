/* =====================================================
   表名: dws.dwb_trade_wide_f
   规则: R0001 - 交易宽表全量装配
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 5表JOIN宽表，复杂度未达分段阈值，pay/log收敛用CTE内联处理，商品维取最新有效行，单条INSERT直产目标F表
   ===================================================== */

CREATE TABLE IF NOT EXISTS dws.dwb_trade_wide_f (
    order_id            VARCHAR(64),  /* 订单ID */
    cust_id             VARCHAR(64),  /* 客户ID */
    product_id          VARCHAR(64),  /* 商品ID */
    order_amt           DECIMAL(18,2),  /* 订单金额 */
    order_qty           DECIMAL(18,4),  /* 订单数量 */
    cust_name           VARCHAR(200),  /* 客户名称 */
    cust_level          VARCHAR(10),  /* 客户等级 */
    product_name        VARCHAR(200),  /* 商品名称 */
    category_code       VARCHAR(50),  /* 商品分类 */
    total_pay_amt       DECIMAL(18,2),  /* 支付总额 */
    total_ship_fee      DECIMAL(18,2),  /* 运费总额 */
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
COMMENT ON COLUMN dws.dwb_trade_wide_f.order_qty IS '订单数量';
COMMENT ON COLUMN dws.dwb_trade_wide_f.cust_name IS '客户名称';
COMMENT ON COLUMN dws.dwb_trade_wide_f.cust_level IS '客户等级';
COMMENT ON COLUMN dws.dwb_trade_wide_f.product_name IS '商品名称';
COMMENT ON COLUMN dws.dwb_trade_wide_f.category_code IS '商品分类';
COMMENT ON COLUMN dws.dwb_trade_wide_f.total_pay_amt IS '支付总额';
COMMENT ON COLUMN dws.dwb_trade_wide_f.total_ship_fee IS '运费总额';
COMMENT ON COLUMN dws.dwb_trade_wide_f.del_flag IS '删除标识';
COMMENT ON COLUMN dws.dwb_trade_wide_f.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN dws.dwb_trade_wide_f.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN dws.dwb_trade_wide_f.dw_last_update_date IS '更新时间';
