/* R0001: 店铺中心宽表装配
   （以 dim_shop_f 为主表，LEFT JOIN 地区维度取省份名，
    并通过两个 CTE 把订单/评价事实表预聚合到店铺粒度后关联，
    一次产出店铺中心宽表全量字段） */
WITH
/* CTE 1: 订单事实表按 shop_id 预聚合（累计订单数、累计销售额、累计去重购买人数） */
order_agg AS (
    SELECT
        dof.shop_id AS shop_id,
        COUNT(1) AS order_cnt,
        COALESCE(SUM(dof.pay_amount), 0) AS sales_amount,
        COUNT(DISTINCT dof.user_id) AS buyer_cnt
    FROM sdord.dwd_order_f dof
    WHERE dof.del_flag = 'N'
    GROUP BY dof.shop_id
),
/* CTE 2: 评价事实表按 shop_id 预聚合（评价数） */
review_agg AS (
    SELECT
        drf3.shop_id AS shop_id,
        COUNT(1) AS review_cnt
    FROM sdrev.dwd_review_f drf3
    WHERE drf3.del_flag = 'N'
    GROUP BY drf3.shop_id
)

/* 主查询: 主表店铺粒度（无 GROUP BY）+ 地区维度 + 订单/评价 CTE 预聚合结果组装 */
SELECT
    dsf.shop_id AS shop_id,
    COALESCE(dsf.shop_name, '') AS shop_name,
    COALESCE(dsf.company_name, '') AS company_name,
    dsf.open_time AS open_time,
    COALESCE(dsf.province_code, '') AS province_code,
    COALESCE(dsf.shop_score, 0) AS shop_score,
    COALESCE(dsf.service_score, 0) AS service_score,
    COALESCE(dsf.logistics_score, 0) AS logistics_score,
    CASE dsf.shop_type
        WHEN 'FLAGSHIP'  THEN '旗舰店'
        WHEN 'SPECIALTY' THEN '专卖店'
        WHEN 'FRANCHISE' THEN '专营店'
        ELSE '其他'
    END AS shop_type_name,
    CASE dsf.shop_status
        WHEN 'OPEN'    THEN '营业中'
        WHEN 'CLOSED'  THEN '已关闭'
        WHEN 'FROZEN'  THEN '冻结'
        ELSE '其他'
    END AS shop_status_name,
    COALESCE((CURRENT_DATE - CAST(dsf.open_time AS DATE)), 0) AS open_days,
    COALESCE(drf.region_name, '') AS province_name,
    COALESCE(order_agg.order_cnt, 0) AS total_order_cnt,
    COALESCE(order_agg.sales_amount, 0) AS total_sales_amount,
    COALESCE(order_agg.buyer_cnt, 0) AS total_buyer_cnt,
    COALESCE(review_agg.review_cnt, 0) AS review_cnt,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM dim.dim_shop_f dsf
LEFT JOIN dim.dim_region_f drf
    ON dsf.province_code = drf.region_code
    AND drf.del_flag = 'N'
LEFT JOIN order_agg
    ON dsf.shop_id = order_agg.shop_id
LEFT JOIN review_agg
    ON dsf.shop_id = review_agg.shop_id
WHERE dsf.del_flag = 'N';
