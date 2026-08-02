/* R0001: 订单画像中间表（将订单明细事实表按用户聚合收口为用户粒度的订单画像，为最终宽表提供订单域指标及 RFM 打分的输入） */
SELECT
    dof.user_id AS user_id,
    COUNT(1) AS total_order_cnt,
    COALESCE(SUM(dof.pay_amount), 0) AS total_pay_amount,
    MAX(dof.create_time) AS last_order_time,
    MIN(dof.create_time) AS first_order_time,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_f dof
WHERE dof.order_status NOT IN ('CANCELLED', 'DELETED')
GROUP BY dof.user_id;
