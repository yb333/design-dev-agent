/* R0003: 用户中心宽表装配（以 dim_user_f 为主表，左联等级/地区/来源维度表与订单/RFM 中间表，CTE 聚合行为/优惠/退款/购物车事实，计算派生转化率与用户标签，产出最终用户中心宽表） */
WITH
/* CTE behavior_agg: 从 dwd_user_behavior_f 按 user_id 聚合浏览/收藏/加购历史次数 */
behavior_agg AS (
    SELECT
        dub.user_id AS user_id,
        COALESCE(SUM(dub.pv_cnt), 0) AS total_pv_cnt,
        COALESCE(SUM(dub.collect_cnt), 0) AS total_collect_cnt,
        COALESCE(SUM(dub.cart_cnt), 0) AS total_cart_cnt
    FROM sdlog.dwd_user_behavior_f dub
    GROUP BY dub.user_id
),
/* CTE coupon_agg: 从 dwd_coupon_use_f 按 user_id 聚合优惠券使用次数与金额 */
coupon_agg AS (
    SELECT
        dcu.user_id AS user_id,
        COUNT(*) AS coupon_used_cnt,
        COALESCE(SUM(dcu.coupon_amount), 0) AS coupon_total_amount
    FROM sdmar.dwd_coupon_use_f dcu
    GROUP BY dcu.user_id
),
/* CTE refund_agg: 从 dwd_refund_f 按 user_id 聚合退款次数 */
refund_agg AS (
    SELECT
        drf7.user_id AS user_id,
        COUNT(*) AS refund_cnt
    FROM sdref.dwd_refund_f drf7
    GROUP BY drf7.user_id
),
/* CTE cart_agg: 从 dwd_cart_f（过滤 del_flag='N' 有效记录）按 user_id 聚合购物车商品数与金额 */
cart_agg AS (
    SELECT
        dcf.user_id AS user_id,
        COUNT(*) AS cart_product_cnt,
        COALESCE(SUM(dcf.qty * dcf.price), 0) AS cart_total_amount
    FROM sdlog.dwd_cart_f dcf
    WHERE dcf.del_flag = 'N'
    GROUP BY dcf.user_id
)

SELECT
    duf.user_id AS user_id,
    duf.user_name AS user_name,
    /* 手机号脱敏：保留前 3 位与后 4 位，中间用 **** 屏蔽 */
    CONCAT(LEFT(duf.user_phone, 3), '****', RIGHT(duf.user_phone, 4)) AS user_phone_masked,
    /* 性别代码转中文：M→男，F→女，其他→未知 */
    CASE duf.gender
        WHEN 'M' THEN '男'
        WHEN 'F' THEN '女'
        ELSE '未知'
    END AS gender_name,
    duf.birthday AS birthday,
    /* 年龄 = 当前年份 - 出生年份（按年粗算，未做生日日精确校验） */
    YEAR(CURDATE()) - YEAR(duf.birthday) AS age,
    duf.register_time AS register_time,
    /* 注册天数 = 当前日期 - 注册日期 */
    DATEDIFF(CURDATE(), duf.register_time) AS register_days,
    duf.last_login_time AS last_login_time,
    duf.level_id AS level_id,
    dul.level_name AS level_name,
    dul.min_points AS level_min_points,
    duf.province_code AS province_code,
    drf.region_name AS province_name,
    duf.city_code AS city_code,
    /* 城市名称：通过 city_code 二次关联 dim_region_f（drf_city 别名）取城市名称，与省份关联分开 */
    drf_city.region_name AS city_name,
    dus.source_name AS source_name,
    duf.member_points AS member_points,
    duf.member_balance AS member_balance,
    /* 用户状态代码转中文：ACTIVE→正常，INACTIVE→未激活，FROZEN→冻结，其他→其他 */
    CASE duf.user_status
        WHEN 'ACTIVE' THEN '正常'
        WHEN 'INACTIVE' THEN '未激活'
        WHEN 'FROZEN' THEN '冻结'
        ELSE '其他'
    END AS user_status_name,
    COALESCE(behavior_agg.total_pv_cnt, 0) AS total_pv_cnt,
    COALESCE(behavior_agg.total_collect_cnt, 0) AS total_collect_cnt,
    COALESCE(behavior_agg.total_cart_cnt, 0) AS total_cart_cnt,
    /* 浏览-下单转化率(%) = 历史订单数 / 浏览次数 × 100；NULLIF 防除零，分母为 0 时返回 NULL */
    COALESCE(tmp1.total_order_cnt, 0) * 100 / NULLIF(COALESCE(behavior_agg.total_pv_cnt, 0), 0) AS pv_to_order_rate,
    /* 浏览-加购转化率(%) = 加购次数 / 浏览次数 × 100；NULLIF 防除零，分母为 0 时返回 NULL */
    COALESCE(behavior_agg.total_cart_cnt, 0) * 100 / NULLIF(COALESCE(behavior_agg.total_pv_cnt, 0), 0) AS pv_to_cart_rate,
    COALESCE(coupon_agg.coupon_used_cnt, 0) AS coupon_used_cnt,
    COALESCE(coupon_agg.coupon_total_amount, 0) AS coupon_total_amount,
    COALESCE(refund_agg.refund_cnt, 0) AS refund_cnt,
    /* 退款率(%) = 退款次数 / 历史订单数 × 100；NULLIF 防除零，分母为 0 时返回 NULL */
    COALESCE(refund_agg.refund_cnt, 0) * 100 / NULLIF(COALESCE(tmp1.total_order_cnt, 0), 0) AS refund_rate,
    COALESCE(cart_agg.cart_product_cnt, 0) AS cart_product_cnt,
    COALESCE(cart_agg.cart_total_amount, 0) AS cart_total_amount,
    /* 下单频率标签：按订单数阶梯判定，前置优先（≥10→高频 > ≥3→中频 > ≥1→低频 > 未购买） */
    CASE
        WHEN COALESCE(tmp1.total_order_cnt, 0) >= 10 THEN '高频用户'
        WHEN COALESCE(tmp1.total_order_cnt, 0) >= 3 THEN '中频用户'
        WHEN COALESCE(tmp1.total_order_cnt, 0) >= 1 THEN '低频用户'
        ELSE '未购买'
    END AS order_freq_label,
    /* 消费能力标签：按消费金额阶梯判定，前置优先（≥10000→高消费 > ≥1000→中消费 > ≥100→低消费 > 无消费） */
    CASE
        WHEN COALESCE(tmp1.total_pay_amount, 0) >= 10000 THEN '高消费'
        WHEN COALESCE(tmp1.total_pay_amount, 0) >= 1000 THEN '中消费'
        WHEN COALESCE(tmp1.total_pay_amount, 0) >= 100 THEN '低消费'
        ELSE '无消费'
    END AS consume_level_label,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM dim.dim_user_f duf
LEFT JOIN dim.dim_user_level_f dul
    ON duf.level_id = dul.level_id
LEFT JOIN dim.dim_region_f drf
    ON duf.province_code = drf.region_code
LEFT JOIN dim.dim_region_f drf_city
    ON duf.city_code = drf_city.region_code
LEFT JOIN dim.dim_user_source_f dus
    ON duf.source_id = dus.source_id
LEFT JOIN slusr.dwb_user_center_f_tmp1 tmp1
    ON duf.user_id = tmp1.user_id
LEFT JOIN slusr.dwb_user_center_f_tmp2 tmp2
    ON duf.user_id = tmp2.user_id
LEFT JOIN behavior_agg
    ON duf.user_id = behavior_agg.user_id
LEFT JOIN coupon_agg
    ON duf.user_id = coupon_agg.user_id
LEFT JOIN refund_agg
    ON duf.user_id = refund_agg.user_id
LEFT JOIN cart_agg
    ON duf.user_id = cart_agg.user_id
