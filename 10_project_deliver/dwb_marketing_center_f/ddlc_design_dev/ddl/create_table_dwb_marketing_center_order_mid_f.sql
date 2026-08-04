/* =====================================================
   表名: slmar.dwb_marketing_center_order_mid_f
   规则: R0001 - 订单指标预聚合
   分布键: activity_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 按 activity_id 预聚合订单指标(订单数/GMV/参与人数/优惠金额/新客占比), 将 dwd_order_f 多行(每笔订单)收敛为一行(每个活动), 防止主查询关联订单表时发散。中间表粒度=每行一个活动, 以 activity_id 为聚合键(隐式粒度键, 非 field_targets 所属)。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slmar.dwb_marketing_center_order_mid_f (
    order_cnt             int,
    gmv_amount            decimal(18,2),
    participant_cnt       int,
    total_discount_amount decimal(18,2),
    new_user_rate         decimal(5,2),
    /* 审计字段 */
    del_flag              NVARCHAR(1),
    crt_cycle_id          BIGINT,
    last_upd_cycle_id     BIGINT,
    dw_last_update_date   TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(activity_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slmar.dwb_marketing_center_order_mid_f IS '营销中心宽表';

COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.order_cnt IS '活动订单数';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.gmv_amount IS '活动GMV';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.participant_cnt IS '参与人数';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.total_discount_amount IS '活动优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.new_user_rate IS '新客占比(%)';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_f.dw_last_update_date IS '数仓最后更新时间';
