/* =====================================================
   表名: slmar.dwb_marketing_center_f
   规则: R0001 - 营销中心宽表写入
   分布键: activity_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 主查询：以活动事实表(dwd_activity_f)为粒度锚点，LEFT JOIN 活动类型维度表取类型说明、 LEFT JOIN 优惠券维度表取券信息，并 LEFT JOIN 订单指标 CTE(order_agg，由 dwd_order_f 按 activity_id 预聚合得到订单数/GMV/参与人数/优惠金额/新客订单数)取活动级订单指标， 最后在主查询层计算派生比率(优惠券使用率/人均消费/新客占比/活动ROI)，按活动粒度全量覆盖写入宽表。 订单明细经 CTE 收敛后再关联，避免活动行发散。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slmar.dwb_marketing_center_f (
    activity_id           bigint,  /* 活动ID */
    activity_name         varchar(100),  /* 活动名称 */
    activity_type_name    varchar(50),  /* 活动类型 */
    activity_type_desc    varchar(500),  /* 活动类型说明 */
    activity_status_name  varchar(50),  /* 活动状态 */
    start_time            datetime,  /* 开始时间 */
    end_time              datetime,  /* 结束时间 */
    activity_days         int,  /* 活动天数 */
    create_time           datetime,  /* 创建时间 */
    min_amount            decimal(18,2),  /* 最低消费金额 */
    discount_rate         decimal(5,2),  /* 折扣率(%) */
    max_discount          decimal(18,2),  /* 最高优惠金额 */
    coupon_id             bigint,  /* 优惠券ID */
    coupon_name           varchar(100),  /* 优惠券名称 */
    coupon_type_name      varchar(50),  /* 优惠券类型 */
    coupon_total_qty      int,  /* 优惠券发放总量 */
    coupon_used_qty       int,  /* 优惠券已使用量 */
    coupon_use_rate       decimal(5,2),  /* 优惠券使用率(%) */
    order_cnt             int,  /* 活动订单数 */
    gmv_amount            decimal(18,2),  /* 活动GMV */
    participant_cnt       int,  /* 参与人数 */
    total_discount_amount decimal(18,2),  /* 活动优惠金额 */
    new_user_rate         decimal(5,2),  /* 新客占比(%) */
    avg_order_amount      decimal(18,2),  /* 人均消费 */
    activity_roi          decimal(8,2),  /* 活动ROI(%) */
    del_flag              NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id          BIGINT,  /* 创建批次ID */
    last_upd_cycle_id     BIGINT,  /* 最后更新批次ID */
    dw_last_update_date   TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(activity_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slmar.dwb_marketing_center_f IS '营销中心宽表';

COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_id IS '活动ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_name IS '活动名称';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_type_name IS '活动类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_type_desc IS '活动类型说明';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_status_name IS '活动状态';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.start_time IS '开始时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.end_time IS '结束时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_days IS '活动天数';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.create_time IS '创建时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.min_amount IS '最低消费金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.discount_rate IS '折扣率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.max_discount IS '最高优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_id IS '优惠券ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_name IS '优惠券名称';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_type_name IS '优惠券类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_total_qty IS '优惠券发放总量';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_used_qty IS '优惠券已使用量';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_use_rate IS '优惠券使用率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.order_cnt IS '活动订单数';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.gmv_amount IS '活动GMV';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.participant_cnt IS '参与人数';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.total_discount_amount IS '活动优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.new_user_rate IS '新客占比(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.avg_order_amount IS '人均消费';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_roi IS '活动ROI(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.dw_last_update_date IS '数仓最后更新时间';
