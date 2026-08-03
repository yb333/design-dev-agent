/* =====================================================
   表名: slord.dwb_order_center_user_tmp1
   规则: R0001 - 用户画像中间表
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 收口所有按 user_id 聚合的用户画像/历史指标(先聚合再关联)，输出用户粒度，避免直接关联订单发散订单粒度。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_user_tmp1 (
    user_id                 bigint,  /* 用户ID */
    first_order_time        datetime,  /* 首次下单时间 */
    last_order_time         datetime,  /* 最近下单时间 */
    history_order_cnt       int,  /* 历史订单数 */
    history_pay_amount      decimal(18,2),  /* 历史消费金额 */
    history_discount_amount decimal(18,2),  /* 历史优惠金额 */
    avg_order_amount        decimal(18,2),  /* 平均客单价 */
    rfm_segment             varchar(20),  /* 用户RFM分层 */
    is_repeat_user          varchar(1),  /* 是否复购用户 */
    fav_pay_method          varchar(20),  /* 用户常用支付方式 */
    user_coupon_used_cnt    int,  /* 用户优惠券使用次数 */
    user_fav_activity_type  varchar(50),  /* 用户偏好活动类型 */
    user_refund_cnt         int,  /* 用户历史退款次数 */
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
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_order_center_user_tmp1 IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_id IS '用户ID';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.first_order_time IS '首次下单时间';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.last_order_time IS '最近下单时间';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.history_order_cnt IS '历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.history_pay_amount IS '历史消费金额';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.history_discount_amount IS '历史优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.rfm_segment IS '用户RFM分层';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.is_repeat_user IS '是否复购用户';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.fav_pay_method IS '用户常用支付方式';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_coupon_used_cnt IS '用户优惠券使用次数';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_fav_activity_type IS '用户偏好活动类型';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_refund_cnt IS '用户历史退款次数';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.dw_last_update_date IS '数仓最后更新时间';
