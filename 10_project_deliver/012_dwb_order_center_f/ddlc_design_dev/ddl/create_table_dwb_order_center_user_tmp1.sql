/* =====================================================
   表名: slord.dwb_order_center_user_tmp1
   规则: R0001 - 用户画像聚合
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 收口所有按 user_id 聚合的用户级指标（历史订单统计、消费金额、RFM 分层、 常用支付方式、优惠券使用、退款次数、偏好活动类型等），避免在主 INSERT 中 混入聚合后关联逻辑。中间表粒度=一个用户一行，以 user_id 为关联键供主规则 JOIN。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_user_tmp1 (
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
    user_refund_cnt         int,  /* 用户历史退款次数 */
    user_fav_activity_type  varchar(50),  /* 用户偏好活动类型 */
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
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_refund_cnt IS '用户历史退款次数';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.user_fav_activity_type IS '用户偏好活动类型';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_user_tmp1.dw_last_update_date IS '数仓最后更新时间';
