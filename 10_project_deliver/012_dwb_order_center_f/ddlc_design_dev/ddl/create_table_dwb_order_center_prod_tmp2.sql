/* =====================================================
   表名: slord.dwb_order_center_prod_tmp2
   规则: R0002 - 商品画像聚合
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 收口按 product_id 聚合的商品级累计销量与销售额指标。中间表粒度=一个商品一行， 以 product_id 为关联键供主规则 JOIN。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_prod_tmp2 (
    product_sales_cnt    int,  /* 商品累计销量 */
    product_sales_amount decimal(18,2),  /* 商品累计销售额 */
    /* 审计字段 */
    del_flag             NVARCHAR(1),
    crt_cycle_id         BIGINT,
    last_upd_cycle_id    BIGINT,
    dw_last_update_date  TIMESTAMP(0)
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_order_center_prod_tmp2 IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.product_sales_cnt IS '商品累计销量';
COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.product_sales_amount IS '商品累计销售额';
COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_prod_tmp2.dw_last_update_date IS '数仓最后更新时间';
