/* =====================================================
   R0001: 售后服务中心宽表组装
   目标表: slas.dwb_after_sale_center_f
   来源表:
     - sdref.dwd_refund_f (drf, 主表，退款事实)
     - sdord.dwd_order_f (dof, 订单明细，JOIN 前按 order_id 收敛)
     - dim.dim_user_f (duf, 用户维度，唯一)
     - dim.dim_product_f (dpf, 商品维度，唯一)
     - sdcs.dwd_service_ticket_f (dst, 工单，JOIN 前取最新一条)
   粒度: 一行 = 一个售后服务记录（=一个退款记录）
   设计意图: 以退款事实表为主表，左关联订单/用户/商品/工单四表拼装
            售后中心宽表；枚举字段中文化，派生处理天数与退款比例
   ===================================================== */
WITH
/* CTE 1: dof 收敛至订单粒度（关联安全）
   dwd_order_f 为订单明细事实表，order_id 可能一对多（一个订单多行明细）；
   按 order_id 聚合：order_no 取唯一值(MIN)、pay_amount 订单级汇总(SUM)，避免退款记录 fan-out */
dof AS (
    SELECT
        order_id,
        MIN(order_no) AS order_no,
        SUM(pay_amount) AS pay_amount
    FROM sdord.dwd_order_f
    WHERE del_flag = 'N'
    GROUP BY order_id
),
/* CTE 2: dst 收敛至工单粒度（关联安全）
   dwd_service_ticket_f 一个 refund_id 可能对应多张工单；
   按 create_time 倒序取最新一条工单(rn=1)，输出 ticket_id/ticket_status/handler_name，避免行数放大 */
dst AS (
    SELECT
        refund_id,
        ticket_id,
        ticket_status,
        handler_name
    FROM (
        SELECT
            refund_id,
            ticket_id,
            ticket_status,
            handler_name,
            ROW_NUMBER() OVER (PARTITION BY refund_id ORDER BY create_time DESC NULLS LAST) AS rn
        FROM sdcs.dwd_service_ticket_f
        WHERE del_flag = 'N'
    ) t
    WHERE t.rn = 1
)

SELECT
    drf.refund_id AS refund_id,
    drf.refund_no AS refund_no,
    CASE drf.refund_type
        WHEN 'ONLY_REFUND' THEN '仅退款'
        WHEN 'RETURN_REFUND' THEN '退货退款'
        WHEN 'EXCHANGE' THEN '换货'
        ELSE '其他'
    END AS refund_type_name,
    CASE drf.refund_status
        WHEN 'APPLYING' THEN '申请中'
        WHEN 'APPROVED' THEN '已同意'
        WHEN 'SUCCESS' THEN '退款成功'
        WHEN 'REJECTED' THEN '已拒绝'
        ELSE '其他'
    END AS refund_status_name,
    drf.apply_time AS apply_time,
    drf.complete_time AS complete_time,
    /* 处理天数: 完成时间 - 申请时间的日期差；退款未完成(完成时间为空)则以当前日期替代完成时间 */
    COALESCE(
        (CAST(COALESCE(drf.complete_time, CURRENT_DATE) AS DATE)
            - CAST(drf.apply_time AS DATE)),
        0
    ) AS process_days,
    COALESCE(drf.refund_amount, 0) AS refund_amount,
    drf.refund_reason AS refund_reason,
    drf.order_id AS order_id,
    drf.user_id AS user_id,
    drf.product_id AS product_id,
    COALESCE(dof.order_no, '') AS order_no,
    COALESCE(dof.pay_amount, 0) AS order_pay_amount,
    /* 退款比例(%): 退款金额/订单实付金额*100，保留两位小数；订单实付金额为0或空时记0以规避除零 */
    CASE
        WHEN COALESCE(dof.pay_amount, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(drf.refund_amount, 0) * 100.0 / dof.pay_amount, 2)
    END AS refund_rate,
    COALESCE(duf.user_name, '') AS user_name,
    COALESCE(dpf.product_name, '') AS product_name,
    dst.ticket_id AS ticket_id,
    CASE dst.ticket_status
        WHEN 'PENDING' THEN '待处理'
        WHEN 'PROCESSING' THEN '处理中'
        WHEN 'RESOLVED' THEN '已解决'
        WHEN 'CLOSED' THEN '已关闭'
        ELSE '其他'
    END AS ticket_status_name,
    COALESCE(dst.handler_name, '') AS handler_name,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdref.dwd_refund_f drf
LEFT JOIN dof ON drf.order_id = dof.order_id
LEFT JOIN dim.dim_user_f duf ON drf.user_id = duf.user_id AND duf.del_flag = 'N'
LEFT JOIN dim.dim_product_f dpf ON drf.product_id = dpf.product_id AND dpf.del_flag = 'N'
LEFT JOIN dst ON drf.refund_id = dst.refund_id
WHERE drf.del_flag = 'N';
