/* I视图: slusr.dwb_user_center_i（用户中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slusr.dwb_user_center_i AS
SELECT
    user_id,
    user_name,
    user_phone_masked,
    gender_name,
    birthday,
    age,
    register_time,
    register_days,
    last_login_time,
    level_id,
    level_name,
    level_min_points,
    province_code,
    province_name,
    city_code,
    city_name,
    source_name,
    member_points,
    member_balance,
    user_status_name,
    total_pv_cnt,
    total_collect_cnt,
    total_cart_cnt,
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

COMMENT ON COLUMN slusr.dwb_user_center_i.user_id IS '用户ID';
COMMENT ON COLUMN slusr.dwb_user_center_i.user_name IS '用户姓名';
COMMENT ON COLUMN slusr.dwb_user_center_i.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_center_i.gender_name IS '性别';
COMMENT ON COLUMN slusr.dwb_user_center_i.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_center_i.age IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_center_i.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_center_i.register_days IS '注册天数';
COMMENT ON COLUMN slusr.dwb_user_center_i.last_login_time IS '最近登录时间';
COMMENT ON COLUMN slusr.dwb_user_center_i.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_center_i.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_center_i.level_min_points IS '等级所需积分';
COMMENT ON COLUMN slusr.dwb_user_center_i.province_code IS '省份编码';
COMMENT ON COLUMN slusr.dwb_user_center_i.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_center_i.city_code IS '城市编码';
COMMENT ON COLUMN slusr.dwb_user_center_i.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_center_i.source_name IS '注册来源';
COMMENT ON COLUMN slusr.dwb_user_center_i.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_center_i.member_balance IS '会员余额';
COMMENT ON COLUMN slusr.dwb_user_center_i.user_status_name IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_center_i.total_pv_cnt IS '浏览次数';
COMMENT ON COLUMN slusr.dwb_user_center_i.total_collect_cnt IS '收藏次数';
COMMENT ON COLUMN slusr.dwb_user_center_i.total_cart_cnt IS '加购次数';
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
