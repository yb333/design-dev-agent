/* =====================================================
   表名: slprd.dwb_product_sales_tmp1
   规则: R0001 - 商品销售汇总中间表
   分布键: product_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 把订单明细(多行/商品)按 product_id 聚合到商品粒度，产出销量/销售额/买家数/近30天销量，供 R0003 关联，避免主表行数发散
   ===================================================== */

CREATE TABLE IF NOT EXISTS slprd.dwb_product_sales_tmp1 (
    total_sales_qty    int,  /* 累计销量 */
    total_sales_amount decimal(18,2),  /* 累计销售额 */
    buyer_cnt          int,  /* 购买人数 */
    sales_qty_30d      int,  /* 近30天销量 */
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

COMMENT ON TABLE slprd.dwb_product_sales_tmp1 IS '商品中心宽表';

COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.total_sales_qty IS '累计销量';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.total_sales_amount IS '累计销售额';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.buyer_cnt IS '购买人数';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.sales_qty_30d IS '近30天销量';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_sales_tmp1.dw_last_update_date IS '数仓最后更新时间';
