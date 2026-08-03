/* I视图: slas.dwb_after_sale_center_i（售后服务中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slas.dwb_after_sale_center_i AS
SELECT
    refund_id,
    refund_no,
    refund_type_name,
    refund_status_name,
    apply_time,
    complete_time,
    process_days,
    refund_amount,
    refund_reason,
    order_id,
    user_id,
    product_id,
    order_no,
    order_pay_amount,
    refund_rate,
    user_name,
    product_name,
    ticket_id,
    ticket_status_name,
    handler_name,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slas.dwb_after_sale_center_f;

COMMENT ON TABLE slas.dwb_after_sale_center_i IS '售后服务中心宽表（视图）';

COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_id IS '退款ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_no IS '退款单号';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_type_name IS '退款类型';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_status_name IS '退款状态';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.apply_time IS '申请时间';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.complete_time IS '完成时间';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.process_days IS '处理天数';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_amount IS '退款金额';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_reason IS '退款原因';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.order_id IS '订单ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.user_id IS '用户ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.product_id IS '商品ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.order_no IS '订单号';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.order_pay_amount IS '订单实付金额';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.refund_rate IS '退款比例(%)';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.user_name IS '用户姓名';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.product_name IS '商品名称';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.ticket_id IS '工单ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.ticket_status_name IS '工单状态';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.handler_name IS '处理人';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_i.dw_last_update_date IS '数仓最后更新时间';
