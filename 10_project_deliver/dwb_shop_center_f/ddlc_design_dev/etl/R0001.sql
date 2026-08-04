/* =====================================================
   R0001: 店铺中心宽表组装
   目标表: slshp.dwb_shop_center_f
   设计意图:
     以店铺维度表为主表，LEFT JOIN 地区维度表获取省份名称；
     通过 CTE 预聚合订单/评价事实表到店铺粒度，避免多表直接 JOIN 的 fan-out；
     标量加工字段（类型/状态映射、营业天数）在主表行内计算。
   来源表:
     - dim.dim_shop_f   dsf   (主表)
     - dim.dim_region_f drf   (地区维)
     - sdord.dwd_order_f dof  (订单事实，经 CTE 收敛)
     - sdrev.dwd_review_f drf3 (评价事实，经 CTE 收敛)
   粒度: 一行 = 一个店铺
   ===================================================== */

WITH
/* CTE 1: 订单统计预聚合 —— 从 dwd_order_f 按 shop_id 收敛到店铺粒度
   关联安全策略: 事实表一对多，GROUP BY shop_id 保证 JOIN 键唯一，避免 fan-out */
order_stat AS (
    SELECT
        dof.shop_id AS shop_id,
        COUNT(1) AS total_order_cnt,
        COALESCE(SUM(dof.pay_amount), 0) AS total_sales_amount,
        COUNT(DISTINCT dof.user_id) AS total_buyer_cnt
    FROM sdord.dwd_order_f dof
    WHERE dof.del_flag = 'N'
    GROUP BY dof.shop_id
),

/* CTE 2: 评价统计预聚合 —— 从 dwd_review_f 按 shop_id 收敛到店铺粒度 */
review_stat AS (
    SELECT
        drf3.shop_id AS shop_id,
        COUNT(1) AS review_cnt
    FROM sdrev.dwd_review_f drf3
    WHERE drf3.del_flag = 'N'
    GROUP BY drf3.shop_id
)

/* 主查询: 店铺维为主表，LEFT JOIN 地区维 + 两个预聚合 CTE */
SELECT
    dsf.shop_id AS shop_id,
    dsf.shop_name AS shop_name,
    /* 店铺类型中文映射 */
    CASE dsf.shop_type
        WHEN 'FLAGSHIP'  THEN '旗舰店'
        WHEN 'SPECIALTY' THEN '专卖店'
        WHEN 'FRANCHISE' THEN '专营店'
        ELSE '其他'
    END AS shop_type_name,
    /* 店铺状态中文映射 */
    CASE dsf.shop_status
        WHEN 'OPEN'   THEN '营业中'
        WHEN 'CLOSED' THEN '已关闭'
        WHEN 'FROZEN' THEN '冻结'
        ELSE '其他'
    END AS shop_status_name,
    dsf.company_name AS company_name,
    dsf.open_time AS open_time,
    /* 营业天数 = 当前日期 - 开店日期的天数差（DWS: 日期相减得到天数整型） */
    COALESCE(CAST(CURRENT_DATE - CAST(dsf.open_time AS DATE) AS INT), 0) AS open_days,
    dsf.province_code AS province_code,
    drf.region_name AS province_name,
    dsf.shop_score AS shop_score,
    dsf.service_score AS service_score,
    dsf.logistics_score AS logistics_score,
    /* 订单聚合指标：CTE LEFT JOIN 结果，NULL 兜底为 0 */
    COALESCE(order_stat.total_order_cnt, 0) AS total_order_cnt,
    COALESCE(order_stat.total_sales_amount, 0) AS total_sales_amount,
    COALESCE(order_stat.total_buyer_cnt, 0) AS total_buyer_cnt,
    /* 评价聚合指标：CTE LEFT JOIN 结果，NULL 兜底为 0 */
    COALESCE(review_stat.review_cnt, 0) AS review_cnt,
    /* 审计字段（4个） */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM dim.dim_shop_f dsf
LEFT JOIN dim.dim_region_f drf
    ON dsf.province_code = drf.region_code
    AND drf.del_flag = 'N'
LEFT JOIN order_stat
    ON dsf.shop_id = order_stat.shop_id
LEFT JOIN review_stat
    ON dsf.shop_id = review_stat.shop_id
WHERE dsf.del_flag = 'N';
