/* =====================================================
   R0001: 售后服务中心宽表组装
   目标表: slas.dwb_after_sale_center_f
   粒度:   一行 = 一个售后服务记录（业务键/distribution_key = refund_id）
   设计意图: 以退款事实表 dwd_refund_f 为主表，左关联订单/用户/商品/工单四表
             拼装售后中心宽表。关联安全：dof(订单事实表)、dst(工单事实表)
             关联前需收敛至 order_id / refund_id 唯一粒度，防止 fan-out；
             duf(用户维表)、dpf(商品维表) join_key 唯一，直接关联。
   ===================================================== */
SELECT
    drf.refund_id                                                  AS refund_id,
    COALESCE(drf.refund_no, '')                                    AS refund_no,
    CASE drf.refund_type
        WHEN 'ONLY_REFUND'   THEN '仅退款'
        WHEN 'RETURN_REFUND' THEN '退货退款'
        WHEN 'EXCHANGE'      THEN '换货'
        ELSE '其他'
    END                                                            AS refund_type_name,
    CASE drf.refund_status
        WHEN 'APPLYING' THEN '申请中'
        WHEN 'APPROVED' THEN '已同意'
        WHEN 'SUCCESS'  THEN '退款成功'
        WHEN 'REJECTED' THEN '已拒绝'
        ELSE '其他'
    END                                                            AS refund_status_name,
    drf.apply_time                                                 AS apply_time,
    drf.complete_time                                              AS complete_time,
    /* 处理天数 = 完成日期 - 申请日期；完成时间为空时用当前日期替代，申请时间为空记为 0 */
    COALESCE(
        (COALESCE(drf.complete_time, CURRENT_TIMESTAMP)::date - drf.apply_time::date),
        0
    )                                                              AS process_days,
    COALESCE(drf.refund_amount, 0)                                 AS refund_amount,
    COALESCE(drf.refund_reason, '')                                AS refund_reason,
    drf.order_id                                                   AS order_id,
    drf.user_id                                                    AS user_id,
    drf.product_id                                                 AS product_id,
    COALESCE(dof.order_no, '')                                     AS order_no,
    COALESCE(dof._pay_amount, 0)                                   AS order_pay_amount,
    /* 退款比例(%) = 退款金额 / 订单实付金额 * 100，保留两位小数；实付金额为零或空记为 0 */
    CASE
        WHEN COALESCE(dof._pay_amount, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(drf.refund_amount, 0) / dof._pay_amount * 100, 2)
    END                                                            AS refund_rate,
    COALESCE(duf.user_name, '')                                    AS user_name,
    COALESCE(dpf.product_name, '')                                 AS product_name,
    dst.ticket_id                                                  AS ticket_id,
    CASE dst.ticket_status
        WHEN 'PENDING'    THEN '待处理'
        WHEN 'PROCESSING' THEN '处理中'
        WHEN 'RESOLVED'   THEN '已解决'
        WHEN 'CLOSED'     THEN '已关闭'
        ELSE '其他'
    END                                                            AS ticket_status_name,
    COALESCE(dst.handler_name, '')                                 AS handler_name,
    'N'                                                            AS del_flag,
    '${P_CYCLE_ID}'                                                AS crt_cycle_id,
    '${P_CYCLE_ID}'                                                AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                                              AS dw_last_update_date
FROM sdref.dwd_refund_f drf
/* dof(订单事实表)按 order_id 收敛至订单粒度：order_no 取唯一值、pay_amount 取订单实付金额，
   保证每个 order_id 只出一行，避免订单明细一对多造成退款记录 fan-out */
LEFT JOIN (
    SELECT
        order_id,
        MAX(order_no)   AS order_no,
        MAX(pay_amount) AS _pay_amount
    FROM sdord.dwd_order_f
    WHERE del_flag = 'N'
    GROUP BY order_id
) dof ON drf.order_id = dof.order_id
/* duf(用户维表) user_id 唯一，直接关联 */
LEFT JOIN dim.dim_user_f duf
    ON drf.user_id = duf.user_id
    AND duf.del_flag = 'N'
/* dpf(商品维表) product_id 唯一，直接关联 */
LEFT JOIN dim.dim_product_f dpf
    ON drf.product_id = dpf.product_id
    AND dpf.del_flag = 'N'
/* dst(工单事实表)按 refund_id 收敛：一个退款对应多张工单时取最新一条工单
   (ORDER BY ticket_id DESC 取 rn=1)，保证每个 refund_id 只出一行 */
LEFT JOIN (
    SELECT
        refund_id,
        ticket_id,
        ticket_status,
        handler_name,
        ROW_NUMBER() OVER (PARTITION BY refund_id ORDER BY ticket_id DESC) AS _rn
    FROM sdcs.dwd_service_ticket_f
    WHERE del_flag = 'N'
) dst ON drf.refund_id = dst.refund_id AND dst._rn = 1
WHERE drf.del_flag = 'N';
