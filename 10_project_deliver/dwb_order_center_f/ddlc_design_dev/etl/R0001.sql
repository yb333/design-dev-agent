/* R0001: 用户画像中间表（收口所有按 user_id 聚合的用户画像/历史指标，先聚合再关联，输出用户粒度，避免直接关联订单发散订单粒度） */
WITH
/* CTE 1: 订单主聚合 - 对 dwd_order_f 按 user_id 收敛，产出首末下单时间/订单数/消费金额/优惠金额 */
dof_agg AS (
    SELECT
        dof.user_id AS user_id,
        MIN(dof.create_time) AS first_order_time,
        MAX(dof.create_time) AS last_order_time,
        COUNT(1) AS history_order_cnt,
        COALESCE(SUM(dof.pay_amount), 0) AS history_pay_amount,
        COALESCE(SUM(dof.discount_amount), 0) AS history_discount_amount
    FROM sdord.dwd_order_f dof
    WHERE dof.order_status NOT IN ('CANCELLED', 'DELETED')
      AND dof.del_flag = 'N'
    GROUP BY dof.user_id
),
/* CTE 2: 支付方式众数 - 对 dwd_payment_f 按 user_id 分组取使用次数最多的 pay_method，收敛到用户粒度 */
dpf_mode AS (
    SELECT
        t.user_id AS user_id,
        t.pay_method AS fav_pay_method
    FROM (
        SELECT
            dpf.user_id AS user_id,
            dpf.pay_method AS pay_method,
            ROW_NUMBER() OVER (
                PARTITION BY dpf.user_id
                ORDER BY COUNT(1) DESC, MAX(dpf.pay_time) DESC
            ) AS rn
        FROM sdpay.dwd_payment_f dpf
        WHERE dpf.del_flag = 'N'
        GROUP BY dpf.user_id, dpf.pay_method
    ) t
    WHERE t.rn = 1
),
/* CTE 3: 优惠券使用次数 - 对 dwd_coupon_use_f 按 user_id COUNT(DISTINCT coupon_id) 收敛，仅统计已使用 */
dcu_cnt AS (
    SELECT
        dcu.user_id AS user_id,
        COUNT(DISTINCT dcu.coupon_id) AS user_coupon_used_cnt
    FROM sdmar.dwd_coupon_use_f dcu
    WHERE dcu.use_status = 'USED'
      AND dcu.del_flag = 'N'
    GROUP BY dcu.user_id
),
/* CTE 4: 退款次数 - 对 dwd_refund_f 按 user_id COUNT 收敛，仅统计退款成功 */
drf_cnt AS (
    SELECT
        drf17.user_id AS user_id,
        COUNT(1) AS user_refund_cnt
    FROM sdref.dwd_refund_f drf17
    WHERE drf17.refund_status = 'SUCCESS'
      AND drf17.del_flag = 'N'
    GROUP BY drf17.user_id
),
/* CTE 5: 偏好活动类型 - dwd_order_f 关联活动维表后按 user_id 取参与订单数最多的 activity_type */
fav_act AS (
    SELECT
        t.user_id AS user_id,
        t.activity_type AS user_fav_activity_type
    FROM (
        SELECT
            dof.user_id AS user_id,
            daf.activity_type AS activity_type,
            ROW_NUMBER() OVER (
                PARTITION BY dof.user_id
                ORDER BY COUNT(1) DESC, MAX(dof.create_time) DESC
            ) AS rn
        FROM sdord.dwd_order_f dof
        LEFT JOIN dim.dim_activity_f daf
            ON dof.activity_id = daf.activity_id
            AND daf.del_flag = 'N'
        WHERE dof.order_status NOT IN ('CANCELLED', 'DELETED')
          AND dof.del_flag = 'N'
          AND daf.activity_type IS NOT NULL
        GROUP BY dof.user_id, daf.activity_type
    ) t
    WHERE t.rn = 1
)

/* 主查询: 以 dof_agg 为基，LEFT JOIN 各收敛后的用户粒度 CTE，再计算派生指标 */
SELECT
    da.user_id AS user_id,
    da.first_order_time AS first_order_time,
    da.last_order_time AS last_order_time,
    da.history_order_cnt AS history_order_cnt,
    da.history_pay_amount AS history_pay_amount,
    da.history_discount_amount AS history_discount_amount,
    CASE
        WHEN COALESCE(da.history_order_cnt, 0) = 0 THEN 0
        ELSE ROUND(da.history_pay_amount / da.history_order_cnt, 2)
    END AS avg_order_amount,
    CONCAT(
        CASE
            WHEN da.last_order_time IS NULL THEN '1'
            WHEN (CURRENT_DATE - CAST(da.last_order_time AS DATE)) <= 30 THEN '5'
            WHEN (CURRENT_DATE - CAST(da.last_order_time AS DATE)) <= 90 THEN '4'
            WHEN (CURRENT_DATE - CAST(da.last_order_time AS DATE)) <= 180 THEN '3'
            WHEN (CURRENT_DATE - CAST(da.last_order_time AS DATE)) <= 365 THEN '2'
            ELSE '1'
        END,
        CASE
            WHEN da.history_order_cnt >= 20 THEN '5'
            WHEN da.history_order_cnt >= 10 THEN '4'
            WHEN da.history_order_cnt >= 5 THEN '3'
            WHEN da.history_order_cnt >= 2 THEN '2'
            ELSE '1'
        END,
        CASE
            WHEN da.history_pay_amount >= 10000 THEN '5'
            WHEN da.history_pay_amount >= 5000 THEN '4'
            WHEN da.history_pay_amount >= 2000 THEN '3'
            WHEN da.history_pay_amount >= 500 THEN '2'
            ELSE '1'
        END
    ) AS rfm_segment,
    CASE
        WHEN da.history_order_cnt >= 2 THEN 'Y'
        ELSE 'N'
    END AS is_repeat_user,
    COALESCE(pm.fav_pay_method, '') AS fav_pay_method,
    COALESCE(dcc.user_coupon_used_cnt, 0) AS user_coupon_used_cnt,
    COALESCE(fa.user_fav_activity_type, '') AS user_fav_activity_type,
    COALESCE(drc.user_refund_cnt, 0) AS user_refund_cnt,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM dof_agg da
LEFT JOIN dpf_mode pm ON da.user_id = pm.user_id
LEFT JOIN dcu_cnt dcc ON da.user_id = dcc.user_id
LEFT JOIN drf_cnt drc ON da.user_id = drc.user_id
LEFT JOIN fav_act fa ON da.user_id = fa.user_id
;
