/* =====================================================
   表名: slmar.dwb_marketing_order_tmp
   规则: R0001 - 活动订单指标中间表
   分布键: activity_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 将订单明细事实表按活动ID聚合收口到活动粒度，产出订单域核心指标（订单数/GMV/参与人数/优惠金额/新客占比），为最终宽表提供订单指标输入
   ===================================================== */

CREATE TABLE IF NOT EXISTS slmar.dwb_marketing_order_tmp (
    order_cnt             int,  /* 活动订单数 */
    gmv_amount            decimal(18,2),  /* 活动GMV */
    participant_cnt       int,  /* 参与人数 */
    total_discount_amount decimal(18,2),  /* 活动优惠金额 */
    new_user_rate         decimal(5,2),  /* 新客占比(%) */
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

COMMENT ON TABLE slmar.dwb_marketing_order_tmp IS '营销中心宽表';

COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.order_cnt IS '活动订单数';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.gmv_amount IS '活动GMV';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.participant_cnt IS '参与人数';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.total_discount_amount IS '活动优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.new_user_rate IS '新客占比(%)';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slmar.dwb_marketing_order_tmp.dw_last_update_date IS '数仓最后更新时间';
