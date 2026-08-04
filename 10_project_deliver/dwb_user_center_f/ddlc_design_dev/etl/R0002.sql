/* R0002: RFM 评分中间表（基于 R0001 订单聚合指标，用 NTILE(5) 窗口函数跨全量用户打分，产出 RFM 三维分数与价值分层） */
WITH
/* CTE order_agg: 引用 R0001 产出的 dwb_user_center_f_tmp1 订单聚合结果，并计算 R 值（最近下单距今天数） */
order_agg AS (
    SELECT
        tmp1.user_id AS user_id,
        tmp1.total_order_cnt AS total_order_cnt,
        tmp1.total_pay_amount AS total_pay_amount,
        /* R 值 = 当前日期 - 最近下单时间的天数；越小代表越近消费（越优） */
        DATEDIFF(CURDATE(), tmp1.last_order_time) AS r_days
    FROM slusr.dwb_user_center_f_tmp1 tmp1
    WHERE tmp1.del_flag = 'N'
),
/* CTE rfm_scores: 在全量用户范围内对 R/F/M 三个维度分别用 NTILE(5) 窗口函数打 1~5 分 */
rfm_scores AS (
    SELECT
        user_id,
        /* R 分：NTILE(5) 升序把天数最小的分到第 1 组；语义要求天数越小分数越高（5→1），用 6 - NTILE(...) 反转 */
        (6 - NTILE(5) OVER (ORDER BY r_days ASC NULLS LAST)) AS r_score,
        /* F 分：按订单数降序，订单越多分越高（直接降序即高分在前，无需反转） */
        NTILE(5) OVER (ORDER BY total_order_cnt DESC NULLS LAST) AS f_score,
        /* M 分：按金额降序，金额越高分越高（直接降序即高分在前，无需反转） */
        NTILE(5) OVER (ORDER BY total_pay_amount DESC NULLS LAST) AS m_score
    FROM order_agg
)

SELECT
    rfm_scores.user_id AS user_id,
    rfm_scores.r_score AS rfm_r_score,
    rfm_scores.f_score AS rfm_f_score,
    rfm_scores.m_score AS rfm_m_score,
    /* 价值分层判定顺序：高价值 > 流失 > 中价值 > 低价值（前置优先，避免相互覆盖） */
    CASE
        /* 高价值：R/F/M 三维均 ≥ 4 */
        WHEN rfm_scores.r_score >= 4
         AND rfm_scores.f_score >= 4
         AND rfm_scores.m_score >= 4 THEN '高价值'
        /* 流失：R ≤ 2 且 F ≤ 2（长期未消费且频次低），优先于中/低价值判定 */
        WHEN rfm_scores.r_score <= 2
         AND rfm_scores.f_score <= 2 THEN '流失'
        /* 中价值：R/F/M 任两维 ≥ 4 */
        WHEN (rfm_scores.r_score >= 4 AND rfm_scores.f_score >= 4)
          OR (rfm_scores.r_score >= 4 AND rfm_scores.m_score >= 4)
          OR (rfm_scores.f_score >= 4 AND rfm_scores.m_score >= 4) THEN '中价值'
        /* 低价值：任一维 ≥ 3（兜底 ELSE 同样归入低价值，确保非空） */
        WHEN rfm_scores.r_score >= 3
          OR rfm_scores.f_score >= 3
          OR rfm_scores.m_score >= 3 THEN '低价值'
        ELSE '低价值'
    END AS rfm_segment,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM rfm_scores
