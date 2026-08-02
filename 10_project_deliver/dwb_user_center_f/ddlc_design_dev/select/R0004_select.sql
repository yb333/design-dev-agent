/* =====================================================
   R0004: 用户中心宽表组装
   目标表: slusr.dwb_user_center_f
   设计意图: 以用户维度为主表，关联等级/地区/来源维度及
             三张画像中间表，装配全部用户中心宽表字段
             （直取+加工+派生+RFM打分+审计）
   加载策略: 全量调度
   ===================================================== */
WITH
/* CTE: 对订单画像中间表在全量用户范围内做 R/F/M 三维 5 档分位数排名
        仅有订单数据的用户参与打分；主查询 LEFT JOIN 后无订单用户的 rfm_*_score 为 NULL */
rfm_scoring AS (
    SELECT
        user_id,
        /* R 值：最近下单距今天数越小越近分数越高，NTILE 升序后取反为高分档 */
        6 - NTILE(5) OVER (ORDER BY (CURRENT_DATE - last_order_time::date) ASC NULLS LAST) AS rfm_r_score,
        /* F 值：历史订单数越大分数越高 */
        NTILE(5) OVER (ORDER BY total_order_cnt DESC NULLS LAST) AS rfm_f_score,
        /* M 值：历史消费金额越大分数越高 */
        NTILE(5) OVER (ORDER BY total_pay_amount DESC NULLS LAST) AS rfm_m_score
    FROM slusr.dwb_user_order_tmp
    WHERE del_flag = 'N'
)

SELECT
    /* —— 直取字段（用户维度主表） —— */
    duf.user_id AS user_id,
    COALESCE(duf.user_name, '') AS user_name,
    duf.birthday AS birthday,
    duf.register_time AS register_time,
    duf.last_login_time AS last_login_time,
    duf.level_id AS level_id,
    duf.province_code AS province_code,
    duf.city_code AS city_code,
    COALESCE(duf.member_points, 0) AS member_points,
    COALESCE(duf.member_balance, 0) AS member_balance,

    /* —— 直取字段（关联维度表） —— */
    COALESCE(dul.level_name, '') AS level_name,
    COALESCE(dul.min_points, 0) AS level_min_points,
    /* 地区表第一次关联（省份层级），取省份名称 */
    COALESCE(drf_prov.region_name, '') AS province_name,
    /* 地区表第二次关联（城市层级），取城市名称 */
    COALESCE(drf_city.region_name, '') AS city_name,
    COALESCE(dus.source_name, '') AS source_name,

    /* —— 加工字段（主表派生） —— */
    /* 手机号脱敏：保留前 3 位 + **** + 后 4 位 */
    COALESCE(CONCAT(LEFT(duf.user_phone, 3), '****', RIGHT(duf.user_phone, 4)), '') AS user_phone_masked,
    /* 性别字典翻译 */
    CASE duf.gender
        WHEN 'M' THEN '男'
        WHEN 'F' THEN '女'
        ELSE '未知'
    END AS gender_name,
    /* 年龄：当前日期与出生日期的年份差 */
    COALESCE(DATE_PART('year', AGE(CURRENT_DATE, duf.birthday)), 0)::int AS age,
    /* 注册天数：注册时间距今天数 */
    COALESCE(CURRENT_DATE - duf.register_time::date, 0) AS register_days,
    /* 用户状态字典翻译 */
    CASE duf.user_status
        WHEN 'ACTIVE' THEN '正常'
        WHEN 'INACTIVE' THEN '未激活'
        WHEN 'FROZEN' THEN '冻结'
        ELSE '其他'
    END AS user_status_name,

    /* —— 派生比率字段（除零保护：分母为 0 时返回 NULL） —— */
    /* 平均客单价：历史消费金额 / 历史订单数 */
    ot.total_pay_amount / NULLIF(ot.total_order_cnt, 0) AS avg_order_amount,
    /* 浏览-下单转化率(%)：订单数 / 浏览次数 * 100 */
    ot.total_order_cnt * 100.0 / NULLIF(bt.total_pv_cnt, 0) AS pv_to_order_rate,
    /* 浏览-加购转化率(%)：加购次数 / 浏览次数 * 100 */
    bt.total_cart_cnt * 100.0 / NULLIF(bt.total_pv_cnt, 0) AS pv_to_cart_rate,
    /* 退款率(%)：退款次数 / 历史订单数 * 100 */
    mt.refund_cnt * 100.0 / NULLIF(ot.total_order_cnt, 0) AS refund_rate,

    /* —— 标签字段（CASE WHEN 分档） —— */
    /* 下单频率标签：按历史订单数分档，0 与 NULL 均走未购买 */
    CASE
        WHEN COALESCE(ot.total_order_cnt, 0) >= 10 THEN '高频用户'
        WHEN COALESCE(ot.total_order_cnt, 0) >= 3 THEN '中频用户'
        WHEN COALESCE(ot.total_order_cnt, 0) >= 1 THEN '低频用户'
        ELSE '未购买'
    END AS order_freq_label,
    /* 消费能力标签：按历史消费金额分档 */
    CASE
        WHEN COALESCE(ot.total_pay_amount, 0) >= 10000 THEN '高消费'
        WHEN COALESCE(ot.total_pay_amount, 0) >= 1000 THEN '中消费'
        WHEN COALESCE(ot.total_pay_amount, 0) >= 100 THEN '低消费'
        ELSE '无消费'
    END AS consume_level_label,

    /* —— RFM 分值（取自 rfm_scoring CTE，无订单用户为 NULL） —— */
    rs.rfm_r_score AS rfm_r_score,
    rs.rfm_f_score AS rfm_f_score,
    rs.rfm_m_score AS rfm_m_score,

    /* —— 用户价值分层（R/F/M 三档组合矩阵） —— */
    CASE
        WHEN COALESCE(rs.rfm_r_score, 0) <= 2 AND COALESCE(rs.rfm_f_score, 0) <= 2 THEN '流失用户'
        WHEN COALESCE(rs.rfm_r_score, 0) >= 4
             AND COALESCE(rs.rfm_f_score, 0) >= 4
             AND COALESCE(rs.rfm_m_score, 0) >= 4 THEN '高价值'
        WHEN COALESCE(rs.rfm_r_score, 0)
             + COALESCE(rs.rfm_f_score, 0)
             + COALESCE(rs.rfm_m_score, 0) >= 9 THEN '中价值'
        ELSE '低价值'
    END AS rfm_segment,

    /* —— 审计字段 —— */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM dim.dim_user_f duf
LEFT JOIN dim.dim_user_level_f dul
    ON duf.level_id = dul.level_id
    AND dul.del_flag = 'N'
/* 地区表第一次关联：省份 */
LEFT JOIN dim.dim_region_f drf_prov
    ON duf.province_code = drf_prov.region_code
    AND drf_prov.region_level = '省份'
    AND drf_prov.del_flag = 'N'
/* 地区表第二次关联：城市（同表起不同别名） */
LEFT JOIN dim.dim_region_f drf_city
    ON duf.city_code = drf_city.region_code
    AND drf_city.region_level = '城市'
    AND drf_city.del_flag = 'N'
LEFT JOIN dim.dim_user_source_f dus
    ON duf.source_id = dus.source_id
    AND dus.del_flag = 'N'
LEFT JOIN slusr.dwb_user_order_tmp ot
    ON duf.user_id = ot.user_id
    AND ot.del_flag = 'N'
LEFT JOIN slusr.dwb_user_behavior_tmp bt
    ON duf.user_id = bt.user_id
    AND bt.del_flag = 'N'
LEFT JOIN slusr.dwb_user_marketing_tmp mt
    ON duf.user_id = mt.user_id
    AND mt.del_flag = 'N'
LEFT JOIN rfm_scoring rs
    ON duf.user_id = rs.user_id
WHERE duf.del_flag = 'N';
