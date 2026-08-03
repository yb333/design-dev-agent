/* =====================================================
   表名: slusr.dwb_user_center_f
   规则: R0004 - 用户中心宽表最终装配
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 以 tmp1（用户基础）为主表，LEFT JOIN tmp2（订单）/tmp3（行为）中间表，并通过 CTE 内联聚合优惠券/退款/购物车事实表，计算 RFM 评分、转化率、价值分层等衍生字段，产出最终宽表。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_f (
    avg_order_amount    decimal(18,2),  /* 平均客单价 */
    rfm_r_score         int,  /* RFM-R值 */
    rfm_f_score         int,  /* RFM-F值 */
    rfm_m_score         int,  /* RFM-M值 */
    rfm_segment         varchar(20),  /* 用户价值分层 */
    pv_to_order_rate    decimal(5,2),  /* 浏览-下单转化率(%) */
    pv_to_cart_rate     decimal(5,2),  /* 浏览-加购转化率(%) */
    coupon_used_cnt     int,  /* 优惠券使用次数 */
    coupon_total_amount decimal(18,2),  /* 优惠券使用金额 */
    refund_cnt          int,  /* 退款次数 */
    refund_rate         decimal(5,2),  /* 退款率(%) */
    cart_product_cnt    int,  /* 购物车商品数 */
    cart_total_amount   decimal(18,2),  /* 购物车金额 */
    order_freq_label    varchar(20),  /* 下单频率标签 */
    consume_level_label varchar(20),  /* 消费能力标签 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_f IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_f.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_r_score IS 'RFM-R值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_f_score IS 'RFM-F值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_m_score IS 'RFM-M值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_segment IS '用户价值分层';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_order_rate IS '浏览-下单转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_cart_rate IS '浏览-加购转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.coupon_used_cnt IS '优惠券使用次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.coupon_total_amount IS '优惠券使用金额';
COMMENT ON COLUMN slusr.dwb_user_center_f.refund_cnt IS '退款次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.refund_rate IS '退款率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.cart_product_cnt IS '购物车商品数';
COMMENT ON COLUMN slusr.dwb_user_center_f.cart_total_amount IS '购物车金额';
COMMENT ON COLUMN slusr.dwb_user_center_f.order_freq_label IS '下单频率标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.consume_level_label IS '消费能力标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.dw_last_update_date IS '数仓最后更新时间';
