/* I视图: slusr.dwb_user_center_i（用户中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slusr.dwb_user_center_i AS
SELECT
    avg_order_amount,
    rfm_r_score,
    rfm_f_score,
    rfm_m_score,
    rfm_segment,
    pv_to_order_rate,
    pv_to_cart_rate,
    coupon_used_cnt,
    coupon_total_amount,
    refund_cnt,
    refund_rate,
    cart_product_cnt,
    cart_total_amount,
    order_freq_label,
    consume_level_label,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slusr.dwb_user_center_f;

COMMENT ON TABLE slusr.dwb_user_center_i IS '用户中心宽表（视图）';

COMMENT ON COLUMN slusr.dwb_user_center_i.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slusr.dwb_user_center_i.rfm_r_score IS 'RFM-R值';
COMMENT ON COLUMN slusr.dwb_user_center_i.rfm_f_score IS 'RFM-F值';
COMMENT ON COLUMN slusr.dwb_user_center_i.rfm_m_score IS 'RFM-M值';
COMMENT ON COLUMN slusr.dwb_user_center_i.rfm_segment IS '用户价值分层';
COMMENT ON COLUMN slusr.dwb_user_center_i.pv_to_order_rate IS '浏览-下单转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_i.pv_to_cart_rate IS '浏览-加购转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_i.coupon_used_cnt IS '优惠券使用次数';
COMMENT ON COLUMN slusr.dwb_user_center_i.coupon_total_amount IS '优惠券使用金额';
COMMENT ON COLUMN slusr.dwb_user_center_i.refund_cnt IS '退款次数';
COMMENT ON COLUMN slusr.dwb_user_center_i.refund_rate IS '退款率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_i.cart_product_cnt IS '购物车商品数';
COMMENT ON COLUMN slusr.dwb_user_center_i.cart_total_amount IS '购物车金额';
COMMENT ON COLUMN slusr.dwb_user_center_i.order_freq_label IS '下单频率标签';
COMMENT ON COLUMN slusr.dwb_user_center_i.consume_level_label IS '消费能力标签';
COMMENT ON COLUMN slusr.dwb_user_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_i.dw_last_update_date IS '数仓最后更新时间';
