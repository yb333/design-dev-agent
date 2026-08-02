/* =====================================================
   表名: slprd.dwb_product_review_tmp1
   规则: R0002 - 商品评价汇总中间表
   分布键: product_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 把评价表(多行/商品)按 product_id 聚合到商品粒度，产出评价数/平均评分/好评率，供 R0003 关联，避免主表行数发散
   ===================================================== */

CREATE TABLE IF NOT EXISTS slprd.dwb_product_review_tmp1 (
    review_cnt       int,  /* 评价数 */
    avg_rating       decimal(2,1),  /* 平均评分 */
    good_review_rate decimal(5,2),  /* 好评率(%) */
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

COMMENT ON TABLE slprd.dwb_product_review_tmp1 IS '商品中心宽表';

COMMENT ON COLUMN slprd.dwb_product_review_tmp1.review_cnt IS '评价数';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.avg_rating IS '平均评分';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.good_review_rate IS '好评率(%)';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_review_tmp1.dw_last_update_date IS '数仓最后更新时间';
