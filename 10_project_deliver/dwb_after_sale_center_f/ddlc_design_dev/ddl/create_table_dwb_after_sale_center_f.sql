/* =====================================================
   表名: slas.dwb_after_sale_center_f
   规则: R0001 - 售后服务中心宽表装配
   分布键: refund_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 以退款事实表为主表，左关联订单/用户/商品/工单四表，一次性拼装售后服务中心宽表全量字段；单场景全量覆盖，无分段
   ===================================================== */

CREATE TABLE IF NOT EXISTS slas.dwb_after_sale_center_f (
    refund_id           bigint,
    refund_no           varchar(64),
    apply_time          datetime,
    complete_time       datetime,
    refund_amount       decimal(18,2),
    refund_reason       varchar(200),
    order_id            bigint,
    user_id             bigint,
    product_id          bigint,
    order_no            varchar(64),
    order_pay_amount    decimal(18,2),
    user_name           varchar(100),
    product_name        varchar(200),
    ticket_id           bigint,
    handler_name        varchar(50),
    refund_type_name    varchar(50),
    refund_status_name  varchar(50),
    ticket_status_name  varchar(50),
    process_days        int,
    refund_rate         decimal(5,2),
    del_flag            NVARCHAR(1),
    crt_cycle_id        BIGINT,
    last_upd_cycle_id   BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(refund_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slas.dwb_after_sale_center_f IS '售后服务中心宽表';

COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_id IS '退款ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_no IS '退款单号';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.apply_time IS '申请时间';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.complete_time IS '完成时间';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_amount IS '退款金额';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_reason IS '退款原因';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.order_id IS '订单ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.user_id IS '用户ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.product_id IS '商品ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.order_no IS '订单号';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.order_pay_amount IS '订单实付金额';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.user_name IS '用户姓名';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.product_name IS '商品名称';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.ticket_id IS '工单ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.handler_name IS '处理人';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_type_name IS '退款类型';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_status_name IS '退款状态';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.ticket_status_name IS '工单状态';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.process_days IS '处理天数';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.refund_rate IS '退款比例(%)';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slas.dwb_after_sale_center_f.dw_last_update_date IS '数仓最后更新时间';
