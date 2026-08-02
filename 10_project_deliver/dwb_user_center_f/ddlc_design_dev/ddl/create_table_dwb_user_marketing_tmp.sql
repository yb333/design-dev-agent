/* =====================================================
   表名: slusr.dwb_user_marketing_tmp
   规则: R0003 - 营销画像中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 将优惠券使用、退款、购物车三张事实表各自按用户聚合后合并为用户粒度的营销画像，收口营销域指标
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_marketing_tmp (
    coupon_used_cnt     int,  /* 优惠券使用次数 */
    coupon_total_amount decimal(18,2),  /* 优惠券使用金额 */
    refund_cnt          int,  /* 退款次数 */
    cart_product_cnt    int,  /* 购物车商品数 */
    cart_total_amount   decimal(18,2),  /* 购物车金额 */
    /* 审计字段 */
    del_flag            NVARCHAR(1),
    crt_cycle_id        BIGINT,
    last_upd_cycle_id   BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_marketing_tmp IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.coupon_used_cnt IS '优惠券使用次数';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.coupon_total_amount IS '优惠券使用金额';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.refund_cnt IS '退款次数';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.cart_product_cnt IS '购物车商品数';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.cart_total_amount IS '购物车金额';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_marketing_tmp.dw_last_update_date IS '数仓最后更新时间';
