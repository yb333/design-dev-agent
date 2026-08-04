/* R0001: 订单聚合中间表（将订单明细事实表聚合到用户粒度，产出历史订单统计指标，供 RFM 评分与最终宽表复用） */
SELECT
    dof.user_id AS user_id,
    COUNT(*) AS total_order_cnt,
    COALESCE(SUM(dof.pay_amount), 0) AS total_pay_amount,
    /* 平均客单价 = 总消费金额 / 历史订单数；NULLIF 防除零，分母为 0 时返回 NULL */
    COALESCE(SUM(dof.pay_amount), 0) / NULLIF(COUNT(*), 0) AS avg_order_amount,
    MAX(dof.create_time) AS last_order_time,
    MIN(dof.create_time) AS first_order_time,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_f dof
WHERE dof.order_status NOT IN ('CANCELLED', 'DELETED')
GROUP BY dof.user_id
