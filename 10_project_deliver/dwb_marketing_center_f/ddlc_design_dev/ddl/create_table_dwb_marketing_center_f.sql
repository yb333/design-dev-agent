/* =====================================================
   表名: slmar.dwb_marketing_center_f
   规则: R0002 - 营销中心宽表组装
   分布键: activity_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 以活动事实表(dwd_activity_f)为主表, LEFT JOIN 活动类型维度、优惠券维度和订单聚合中间表, 组装营销中心宽表全部字段。枚举翻译、比率指标、人均消费、ROI 在此规则完成。 订单相关指标全部取自 R0001 中间表, 不再直接关联订单明细表。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slmar.dwb_marketing_center_f (
    activity_id          bigint,
    activity_name        varchar(100),
    activity_type_desc   varchar(500),
    start_time           datetime,
    end_time             datetime,
    create_time          datetime,
    min_amount           decimal(18,2),
    discount_rate        decimal(5,2),
    max_discount         decimal(18,2),
    coupon_id            bigint,
    coupon_name          varchar(100),
    coupon_total_qty     int,
    coupon_used_qty      int,
    activity_type_name   varchar(50),
    activity_status_name varchar(50),
    activity_days        int,
    coupon_type_name     varchar(50),
    coupon_use_rate      decimal(5,2),
    avg_order_amount     decimal(18,2),
    activity_roi         decimal(8,2),
    del_flag             NVARCHAR(1),
    crt_cycle_id         BIGINT,
    last_upd_cycle_id    BIGINT,
    dw_last_update_date  TIMESTAMP(0) WITHOUT TIME ZONE
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
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_type_desc IS '活动类型说明';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.start_time IS '开始时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.end_time IS '结束时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.create_time IS '创建时间';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.min_amount IS '最低消费金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.discount_rate IS '折扣率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.max_discount IS '最高优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_id IS '优惠券ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_name IS '优惠券名称';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_total_qty IS '优惠券发放总量';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_used_qty IS '优惠券已使用量';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_type_name IS '活动类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_status_name IS '活动状态';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_days IS '活动天数';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_type_name IS '优惠券类型';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.coupon_use_rate IS '优惠券使用率(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.avg_order_amount IS '人均消费';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.activity_roi IS '活动ROI(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_f.dw_last_update_date IS '数仓最后更新时间';
