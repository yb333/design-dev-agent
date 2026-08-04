/* R0001: 用户画像汇总
   将订单/支付/优惠券/退款四类事实表按 user_id 聚合，
   产出用户级画像指标（首次/最近下单、历史消费、RFM分层、复购、偏好），
   避免主装配阶段聚合导致粒度发散。目标表: slord.dwb_order_center_tmp1 */

/* CTE 1: 订单核心统计 - 按 user_id 聚合订单时间/订单数/金额汇总 */
WITH cte_order_stats AS (
    SELECT
        user_id,
        MIN(create_time)                  AS first_order_time,
        MAX(create_time)                  AS last_order_time,
        COUNT(*)                          AS history_order_cnt,
        COALESCE(SUM(pay_amount), 0)      AS history_pay_amount,
        COALESCE(SUM(discount_amount), 0) AS history_discount_amount
    FROM sdord.dwd_order_f
    WHERE del_flag = 'N'
      AND order_status NOT IN ('CANCELLED', 'DELETED')
    GROUP BY user_id
),

/* CTE 2: 订单衍生指标 - 客单价 / 复购标识 / RFM 三分量(NTILE 自动5等分) */
cte_order_rfm AS (
    SELECT
        os.user_id,
        os.first_order_time,
        os.last_order_time,
        os.history_order_cnt,
        os.history_pay_amount,
        os.history_discount_amount,
        /* 平均客单价 = 历史消费金额 / 历史订单数 (防除零) */
        CASE
            WHEN os.history_order_cnt = 0 THEN 0
            ELSE ROUND(os.history_pay_amount / os.history_order_cnt, 2)
        END AS avg_order_amount,
        /* 复购用户: 历史订单数 >= 2 */
        CASE WHEN os.history_order_cnt >= 2 THEN 'Y' ELSE 'N' END AS is_repeat_user,
        /* R/F/M 各按数据分布自动5等分 (设计未给阈值, 用 NTILE 兜底) */
        NTILE(5) OVER (ORDER BY os.last_order_time ASC)     AS r_score,
        NTILE(5) OVER (ORDER BY os.history_order_cnt ASC)   AS f_score,
        NTILE(5) OVER (ORDER BY os.history_pay_amount ASC)  AS m_score
    FROM cte_order_stats os
),

/* CTE 3: 活动偏好 - 按 user_id+activity_type 统计参与订单数, 取最多的活动类型 */
cte_activity_pref AS (
    SELECT user_id, activity_type
    FROM (
        SELECT
            user_id,
            activity_type,
            ROW_NUMBER() OVER (
                PARTITION BY user_id
                ORDER BY COUNT(*) DESC, MAX(create_time) DESC
            ) AS rn
        FROM sdord.dwd_order_f
        WHERE del_flag = 'N'
          AND order_status NOT IN ('CANCELLED', 'DELETED')
          AND activity_type IS NOT NULL
        GROUP BY user_id, activity_type
    ) t
    WHERE rn = 1
),

/* CTE 4: 支付偏好 - 按 user_id+pay_method 统计次数, 取使用最多的支付方式 */
cte_pay_pref AS (
    SELECT user_id, pay_method
    FROM (
        SELECT
            user_id,
            pay_method,
            ROW_NUMBER() OVER (
                PARTITION BY user_id
                ORDER BY COUNT(*) DESC, MAX(create_time) DESC
            ) AS rn
        FROM sdpay.dwd_payment_f
        WHERE del_flag = 'N'
          AND pay_status = 'SUCCESS'
        GROUP BY user_id, pay_method
    ) t
    WHERE rn = 1
),

/* CTE 5: 优惠券统计 - 按 user_id 统计 DISTINCT coupon_id 使用次数 */
cte_coupon_stats AS (
    SELECT
        user_id,
        COUNT(DISTINCT coupon_id) AS user_coupon_used_cnt
    FROM sdmar.dwd_coupon_use_f
    WHERE del_flag = 'N'
      AND use_status = 'USED'
    GROUP BY user_id
),

/* CTE 6: 退款统计 - 按 user_id 统计退款成功次数 */
cte_refund_stats AS (
    SELECT
        user_id,
        COUNT(*) AS user_refund_cnt
    FROM sdref.dwd_refund_f
    WHERE del_flag = 'N'
      AND refund_status = 'SUCCESS'
    GROUP BY user_id
)

/* 最终组装: 以 cte_order_rfm 为主表, LEFT JOIN 各 user_id 粒度子聚合 */
SELECT
    rf.user_id AS user_id,
    rf.first_order_time AS first_order_time,
    rf.last_order_time AS last_order_time,
    rf.history_order_cnt AS history_order_cnt,
    rf.history_pay_amount AS history_pay_amount,
    rf.history_discount_amount AS history_discount_amount,
    rf.avg_order_amount AS avg_order_amount,
    /* RFM 三分量组合标签: R{r}F{f}M{m} */
    CONCAT('R', rf.r_score, 'F', rf.f_score, 'M', rf.m_score) AS rfm_segment,
    rf.is_repeat_user AS is_repeat_user,
    /* 常用支付方式, 无支付记录兜底空串 */
    COALESCE(pp.pay_method, '') AS fav_pay_method,
    /* 优惠券使用次数, 无记录兜底 0 */
    COALESCE(cs.user_coupon_used_cnt, 0) AS user_coupon_used_cnt,
    /* 偏好活动类型, 无活动记录兜底空串 */
    COALESCE(ap.activity_type, '') AS user_fav_activity_type,
    /* 历史退款次数, 无退款记录兜底 0 */
    COALESCE(rs.user_refund_cnt, 0) AS user_refund_cnt,
    /* 审计字段 (assemble_ddl.py 会给 tmp 表追加审计列, 必带) */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM cte_order_rfm rf
LEFT JOIN cte_activity_pref ap ON rf.user_id = ap.user_id
LEFT JOIN cte_pay_pref pp     ON rf.user_id = pp.user_id
LEFT JOIN cte_coupon_stats cs ON rf.user_id = cs.user_id
LEFT JOIN cte_refund_stats rs ON rf.user_id = rs.user_id
