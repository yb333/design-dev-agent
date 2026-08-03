/* =====================================================
   表名: slusr.dwb_user_center_tmp2
   规则: R0002 - 订单汇总中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 对 dwd_order_f 排除作废/删除订单后按 user_id 聚合，产出用户级订单汇总指标，供最终装配规则引用。粒度从订单明细收敛到用户。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_tmp2 (
    total_order_cnt  int,  /* 历史订单数 */
    total_pay_amount decimal(18,2),  /* 历史消费金额 */
    last_order_time  datetime,  /* 最近下单时间 */
    first_order_time datetime,  /* 首次下单时间 */
    /* 审计字段 */
    del_flag         NVARCHAR(1),
    crt_cycle_id     BIGINT,
    last_upd_cycle_id BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_tmp2 IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_tmp2.total_order_cnt IS '历史订单数';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.total_pay_amount IS '历史消费金额';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.last_order_time IS '最近下单时间';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.first_order_time IS '首次下单时间';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp2.dw_last_update_date IS '数仓最后更新时间';
