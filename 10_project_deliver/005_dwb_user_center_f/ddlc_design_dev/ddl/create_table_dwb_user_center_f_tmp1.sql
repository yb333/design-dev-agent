/* =====================================================
   表名: slusr.dwb_user_center_f_tmp1
   规则: R0001 - 订单聚合中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 将订单明细事实表聚合到用户粒度，产出历史订单统计指标，供 RFM 评分与最终宽表复用
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_f_tmp1 (
    total_order_cnt  int,  /* 历史订单数 */
    total_pay_amount decimal(18,2),  /* 历史消费金额 */
    avg_order_amount decimal(18,2),  /* 平均客单价 */
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

COMMENT ON TABLE slusr.dwb_user_center_f_tmp1 IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.total_order_cnt IS '历史订单数';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.total_pay_amount IS '历史消费金额';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.last_order_time IS '最近下单时间';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.first_order_time IS '首次下单时间';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp1.dw_last_update_date IS '数仓最后更新时间';
