/* I视图: slmar.dwb_marketing_center_i（营销中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slmar.dwb_marketing_center_i AS
SELECT
    activity_id,
    activity_name,
    activity_type_name,
    activity_type_desc,
    activity_status_name,
    start_time,
    end_time,
    activity_days,
    create_time,
    min_amount,
    discount_rate,
    max_discount,
    coupon_id,
    coupon_name,
    coupon_type_name,
    coupon_total_qty,
    coupon_used_qty,
    coupon_use_rate,
    order_cnt,
    gmv_amount,
    participant_cnt,
    total_discount_amount,
    new_user_rate,
    avg_order_amount,
    activity_roi,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slmar.dwb_marketing_center_f;

COMMENT ON TABLE slmar.dwb_marketing_center_i IS '营销中心宽表（视图）';

COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_id IS '活动ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_name IS '活动名称';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_type_name IS '活动类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_type_desc IS '活动类型说明';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_status_name IS '活动状态';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.start_time IS '开始时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.end_time IS '结束时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_days IS '活动天数';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.create_time IS '创建时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.min_amount IS '最低消费金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.discount_rate IS '折扣率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.max_discount IS '最高优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_id IS '优惠券ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_name IS '优惠券名称';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_type_name IS '优惠券类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_total_qty IS '优惠券发放总量';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_used_qty IS '优惠券已使用量';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.coupon_use_rate IS '优惠券使用率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.order_cnt IS '活动订单数';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.gmv_amount IS '活动GMV';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.participant_cnt IS '参与人数';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.total_discount_amount IS '活动优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.new_user_rate IS '新客占比(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.avg_order_amount IS '人均消费';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.activity_roi IS '活动ROI(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_i.dw_last_update_date IS '数仓最后更新时间';
