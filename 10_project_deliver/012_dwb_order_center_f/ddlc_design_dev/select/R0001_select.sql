/* =====================================================
   R0001: 用户画像聚合（收口所有按 user_id 聚合的用户级指标）
   目标表: slord.dwb_order_center_user_tmp1（中间表，一行=一个用户）
   来源表:
     - sdord.dwd_order_f       (dof)  订单事实，过滤 order_status NOT IN ('CANCELLED','DELETED')
     - sdpay.dwd_payment_f     (dpf)  支付事实，过滤 pay_status='SUCCESS'
     - sdmar.dwd_coupon_use_f  (dcu)  优惠券使用，过滤 use_status='USED'
     - sdref.dwd_refund_f      (drf17)退款事实，过滤 refund_status='SUCCESS'
   关联安全: 4 个源表各自 GROUP BY user_id 收敛后聚合天然唯一，再 LEFT JOIN 组装
   ===================================================== */
WITH
/* CTE 1: 订单基础聚合（按用户收敛） */
order_agg AS (
    SELECT
        dof.user_id                                                    AS user_id,
        MIN(dof.order_time)                                            AS first_order_time,
        MAX(dof.order_time)                                            AS last_order_time,
        COUNT(1)                                                       AS history_order_cnt,
        COALESCE(SUM(dof.pay_amount), 0)                               AS history_pay_amount,
        COALESCE(SUM(dof.discount_amount), 0)                          AS history_discount_amount
    FROM sdord.dwd_order_f dof
    WHERE COALESCE(dof.del_flag, 'N') = 'N'
      AND dof.order_status NOT IN ('CANCELLED', 'DELETED')
    GROUP BY dof.user_id
),
/* CTE 2: 在订单聚合基础上计算 RFM 三项分值（NTILE 5 分位） */
order_rfm AS (
    SELECT
        oa.user_id                                                    AS user_id,
        oa.first_order_time                                           AS first_order_time,
        oa.last_order_time                                            AS last_order_time,
        oa.history_order_cnt                                          AS history_order_cnt,
        oa.history_pay_amount                                         AS history_pay_amount,
        oa.history_discount_amount                                    AS history_discount_amount,
        NTILE(5) OVER (ORDER BY oa.last_order_time ASC)               AS r_score,  /* 越近分越高 */
        NTILE(5) OVER (ORDER BY oa.history_order_cnt ASC)             AS f_score,  /* 越多分越高 */
        NTILE(5) OVER (ORDER BY oa.history_pay_amount ASC)            AS m_score   /* 越大分越高 */
    FROM order_agg oa
),
/* CTE 3: 用户参与各活动类型的订单数 */
activity_cnt AS (
    SELECT
        dof.user_id                                                    AS user_id,
        dof.activity_type                                              AS activity_type,
        COUNT(1)                                                       AS act_order_cnt
    FROM sdord.dwd_order_f dof
    WHERE COALESCE(dof.del_flag, 'N') = 'N'
      AND dof.order_status NOT IN ('CANCELLED', 'DELETED')
      AND dof.activity_type IS NOT NULL
    GROUP BY dof.user_id, dof.activity_type
),
/* CTE 4: 取每个用户参与订单数最多的活动类型（ROW_NUMBER rn=1） */
activity_top AS (
    SELECT
        ac.user_id                                                                   AS user_id,
        ac.activity_type                                                             AS activity_type,
        ROW_NUMBER() OVER (PARTITION BY ac.user_id
                           ORDER BY ac.act_order_cnt DESC, ac.activity_type ASC)    AS rn
    FROM activity_cnt ac
),
/* CTE 5: 用户各支付方式成功支付次数 */
payment_cnt AS (
    SELECT
        dpf.user_id                                                   AS user_id,
        dpf.pay_method                                                AS pay_method,
        COUNT(1)                                                      AS pay_cnt
    FROM sdpay.dwd_payment_f dpf
    WHERE COALESCE(dpf.del_flag, 'N') = 'N'
      AND dpf.pay_status = 'SUCCESS'
    GROUP BY dpf.user_id, dpf.pay_method
),
/* CTE 6: 取每个用户使用频次最高的支付方式（ROW_NUMBER rn=1） */
payment_top AS (
    SELECT
        pc.user_id                                                                AS user_id,
        pc.pay_method                                                             AS pay_method,
        ROW_NUMBER() OVER (PARTITION BY pc.user_id
                           ORDER BY pc.pay_cnt DESC, pc.pay_method ASC)         AS rn
    FROM payment_cnt pc
),
/* CTE 7: 用户已使用优惠券去重计数 */
coupon_agg AS (
    SELECT
        dcu.user_id                                 AS user_id,
        COUNT(DISTINCT dcu.coupon_id)               AS user_coupon_used_cnt
    FROM sdmar.dwd_coupon_use_f dcu
    WHERE COALESCE(dcu.del_flag, 'N') = 'N'
      AND dcu.use_status = 'USED'
    GROUP BY dcu.user_id
),
/* CTE 8: 用户历史成功退款次数 */
refund_agg AS (
    SELECT
        drf17.user_id                               AS user_id,
        COUNT(1)                                    AS user_refund_cnt
    FROM sdref.dwd_refund_f drf17
    WHERE COALESCE(drf17.del_flag, 'N') = 'N'
      AND drf17.refund_status = 'SUCCESS'
    GROUP BY drf17.user_id
)

/* 最终组装：以 order_rfm 为主表，LEFT JOIN 各源收敛后的用户级结果 */
SELECT
    orf.user_id                                                                      AS user_id,
    orf.first_order_time                                                             AS first_order_time,
    orf.last_order_time                                                              AS last_order_time,
    COALESCE(orf.history_order_cnt, 0)                                               AS history_order_cnt,
    COALESCE(orf.history_pay_amount, 0)                                              AS history_pay_amount,
    COALESCE(orf.history_discount_amount, 0)                                         AS history_discount_amount,
    CASE
        WHEN COALESCE(orf.history_order_cnt, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(orf.history_pay_amount, 0) / orf.history_order_cnt, 2)
    END                                                                              AS avg_order_amount,
    (orf.r_score::TEXT || orf.f_score::TEXT || orf.m_score::TEXT)                     AS rfm_segment,
    CASE
        WHEN COALESCE(orf.history_order_cnt, 0) >= 2 THEN 'Y'
        ELSE 'N'
    END                                                                              AS is_repeat_user,
    COALESCE(ptp.pay_method, '')                                                     AS fav_pay_method,
    COALESCE(ca.user_coupon_used_cnt, 0)                                             AS user_coupon_used_cnt,
    COALESCE(ra.user_refund_cnt, 0)                                                  AS user_refund_cnt,
    COALESCE(atp.activity_type, '')                                                  AS user_fav_activity_type,
    'N'                                                                              AS del_flag,
    '${P_CYCLE_ID}'                                                                  AS crt_cycle_id,
    '${P_CYCLE_ID}'                                                                  AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                                                                AS dw_last_update_date
FROM order_rfm orf
LEFT JOIN activity_top atp ON orf.user_id = atp.user_id AND atp.rn = 1
LEFT JOIN payment_top  ptp ON orf.user_id = ptp.user_id AND ptp.rn = 1
LEFT JOIN coupon_agg   ca  ON orf.user_id = ca.user_id
LEFT JOIN refund_agg   ra  ON orf.user_id = ra.user_id;
