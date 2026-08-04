/* R0001: 售后服务中心宽表装配（以退款事实表为主表，左关联订单/用户/商品/工单四表，一次性拼装售后服务中心宽表全量字段；单场景全量覆盖，无分段） */

/* CTE 1: dwd_order_f 按 order_id 聚合到订单粒度（取订单号、汇总实付金额），避免退款行发散 */
WITH dof_agg AS (
    SELECT
        order_id,
        MAX(order_no) AS order_no,
        COALESCE(SUM(pay_amount), 0) AS pay_amount
    FROM sdord.dwd_order_f
    WHERE del_flag = 'N'
    GROUP BY order_id
),

/* CTE 2: dwd_service_ticket_f 按 refund_id 取最新一条有效工单（创建时间倒序取首条），保证每个退款 1:1 关联 */
dst_latest AS (
    SELECT
        refund_id,
        ticket_id,
        handler_name,
        ticket_status,
        ROW_NUMBER() OVER (PARTITION BY refund_id ORDER BY create_time DESC NULLS LAST) AS rn
    FROM sdcs.dwd_service_ticket_f
    WHERE del_flag = 'N'
)

/* 主查询: 退款粒度装配（1:1，无外层 GROUP BY） */
SELECT
    drf.refund_id AS refund_id,
    drf.refund_no AS refund_no,
    drf.apply_time AS apply_time,
    drf.complete_time AS complete_time,
    COALESCE(drf.refund_amount, 0) AS refund_amount,
    COALESCE(drf.refund_reason, '') AS refund_reason,
    drf.order_id AS order_id,
    drf.user_id AS user_id,
    drf.product_id AS product_id,
    COALESCE(dof_agg.order_no, '') AS order_no,
    COALESCE(dof_agg.pay_amount, 0) AS order_pay_amount,
    COALESCE(duf.user_name, '') AS user_name,
    COALESCE(dpf.product_name, '') AS product_name,
    dst.ticket_id AS ticket_id,
    COALESCE(dst.handler_name, '') AS handler_name,
    /* 退款类型码值转换: ONLY_REFUND→仅退款, RETURN_REFUND→退货退款, EXCHANGE→换货, 其余→其他 */
    CASE drf.refund_type
        WHEN 'ONLY_REFUND' THEN '仅退款'
        WHEN 'RETURN_REFUND' THEN '退货退款'
        WHEN 'EXCHANGE' THEN '换货'
        ELSE '其他'
    END AS refund_type_name,
    /* 退款状态码值转换: APPLYING→申请中, APPROVED→已同意, SUCCESS→退款成功, REJECTED→已拒绝, 其余→其他 */
    CASE drf.refund_status
        WHEN 'APPLYING' THEN '申请中'
        WHEN 'APPROVED' THEN '已同意'
        WHEN 'SUCCESS' THEN '退款成功'
        WHEN 'REJECTED' THEN '已拒绝'
        ELSE '其他'
    END AS refund_status_name,
    /* 工单状态码值转换: PENDING→待处理, PROCESSING→处理中, RESOLVED→已解决, CLOSED→已关闭, 其余→其他 */
    CASE dst.ticket_status
        WHEN 'PENDING' THEN '待处理'
        WHEN 'PROCESSING' THEN '处理中'
        WHEN 'RESOLVED' THEN '已解决'
        WHEN 'CLOSED' THEN '已关闭'
        ELSE '其他'
    END AS ticket_status_name,
    /* 处理天数=完成时间与申请时间相差天数；完成时间为空时按当天计算（COALESCE 兜底当前日期） */
    COALESCE(CAST(drf.complete_time AS DATE), CURRENT_DATE) - CAST(drf.apply_time AS DATE) AS process_days,
    /* 退款比例(%)=退款金额/订单实付金额×100；订单实付金额为空或为0时防除零 */
    CASE
        WHEN COALESCE(dof_agg.pay_amount, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(drf.refund_amount, 0) * 100.0 / dof_agg.pay_amount, 2)
    END AS refund_rate,
    /* 审计字段 */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdref.dwd_refund_f drf
LEFT JOIN dof_agg ON drf.order_id = dof_agg.order_id
LEFT JOIN dim.dim_user_f duf ON drf.user_id = duf.user_id AND duf.del_flag = 'N'
LEFT JOIN dim.dim_product_f dpf ON drf.product_id = dpf.product_id AND dpf.del_flag = 'N'
LEFT JOIN dst_latest dst ON drf.refund_id = dst.refund_id AND dst.rn = 1
WHERE drf.del_flag = 'N';
