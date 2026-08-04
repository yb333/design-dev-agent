/* =====================================================
   表名: slord.dwb_order_center_tmp1
   规则: R0001 - 用户画像汇总
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 将订单、支付、优惠券、退款四类事实表按 user_id 聚合，产出用户级画像指标（首次/最近下单、历史消费、RFM分层、复购、偏好），避免主装配阶段聚合导致粒度发散
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_tmp1 (
    first_order_time        datetime,
    last_order_time         datetime,
    history_order_cnt       int,
    history_pay_amount      decimal(18,2),
    history_discount_amount decimal(18,2),
    avg_order_amount        decimal(18,2),
    rfm_segment             varchar(20),
    is_repeat_user          varchar(1),
    fav_pay_method          varchar(20),
    user_coupon_used_cnt    int,
    user_fav_activity_type  varchar(50),
    user_refund_cnt         int,
    /* 审计字段 */
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0)
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_order_center_tmp1 IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_tmp1.first_order_time IS '首次下单时间';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.last_order_time IS '最近下单时间';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.history_order_cnt IS '历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.history_pay_amount IS '历史消费金额';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.history_discount_amount IS '历史优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.rfm_segment IS '用户RFM分层';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.is_repeat_user IS '是否复购用户';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.fav_pay_method IS '用户常用支付方式';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.user_coupon_used_cnt IS '用户优惠券使用次数';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.user_fav_activity_type IS '用户偏好活动类型';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.user_refund_cnt IS '用户历史退款次数';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_tmp1.dw_last_update_date IS '数仓最后更新时间';
