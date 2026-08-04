/* =====================================================
   表名: slprd.dwb_product_center_tmp1
   规则: R0001 - 订单销售汇总
   分布键: product_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 将订单明细按商品粒度聚合，收口为每商品一行的销售指标，解耦主规则的聚合复杂度
   ===================================================== */

CREATE TABLE IF NOT EXISTS slprd.dwb_product_center_tmp1 (
    total_sales_qty    int,
    total_sales_amount decimal(18,2),
    buyer_cnt          int,
    sales_qty_30d      int,
    /* 审计字段 */
    del_flag           NVARCHAR(1),
    crt_cycle_id       BIGINT,
    last_upd_cycle_id  BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(product_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slprd.dwb_product_center_tmp1 IS '商品中心宽表';

COMMENT ON COLUMN slprd.dwb_product_center_tmp1.total_sales_qty IS '累计销量';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.total_sales_amount IS '累计销售额';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.buyer_cnt IS '购买人数';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.sales_qty_30d IS '近30天销量';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_tmp1.dw_last_update_date IS '数仓最后更新时间';
