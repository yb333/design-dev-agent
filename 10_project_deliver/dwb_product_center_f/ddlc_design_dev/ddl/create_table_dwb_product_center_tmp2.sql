/* =====================================================
   表名: slprd.dwb_product_center_tmp2
   规则: R0002 - 评价汇总
   分布键: product_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 将评价明细按商品粒度聚合，收口为每商品一行的评价指标，与订单汇总并行执行
   ===================================================== */

CREATE TABLE IF NOT EXISTS slprd.dwb_product_center_tmp2 (
    review_cnt       int,
    avg_rating       decimal(2,1),
    good_review_rate decimal(5,2),
    /* 审计字段 */
    del_flag         NVARCHAR(1),
    crt_cycle_id     BIGINT,
    last_upd_cycle_id BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(product_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slprd.dwb_product_center_tmp2 IS '商品中心宽表';

COMMENT ON COLUMN slprd.dwb_product_center_tmp2.review_cnt IS '评价数';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.avg_rating IS '平均评分';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.good_review_rate IS '好评率(%)';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_tmp2.dw_last_update_date IS '数仓最后更新时间';
