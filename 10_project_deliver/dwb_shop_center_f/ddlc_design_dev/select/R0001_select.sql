/* R0001: 店铺中心宽表加工（以 dim_shop_f 为主表，LEFT JOIN dim_region_f 取省份名称；
   订单明细/评价明细经 CTE 按 shop_id 聚合收敛到店铺粒度后再关联，一次性产出店铺级宽表） */

/* CTE 1: 订单明细按 shop_id 收敛 → 累计订单数/累计销售额/累计购买人数 */
WITH order_agg AS (
    SELECT
        dof.shop_id AS shop_id,
        COUNT(1) AS total_order_cnt,
        COALESCE(SUM(dof.pay_amount), 0) AS total_sales_amount,
        COUNT(DISTINCT dof.user_id) AS total_buyer_cnt
    FROM sdord.dwd_order_f dof
    WHERE dof.del_flag = 'N'
    GROUP BY dof.shop_id
),

/* CTE 2: 评价明细按 shop_id 收敛 → 评价数 */
review_agg AS (
    SELECT
        drf5.shop_id AS shop_id,
        COUNT(1) AS review_cnt
    FROM sdrev.dwd_review_f drf5
    WHERE drf5.del_flag = 'N'
    GROUP BY drf5.shop_id
)

/* 主查询: 主表为店铺粒度，安全 LEFT JOIN 各收敛后结果 */
SELECT
    dsf.shop_id AS shop_id,
    dsf.shop_name AS shop_name,
    dsf.company_name AS company_name,
    dsf.open_time AS open_time,
    dsf.province_code AS province_code,
    dsf.shop_score AS shop_score,
    dsf.service_score AS service_score,
    dsf.logistics_score AS logistics_score,
    CASE dsf.shop_type
        WHEN 'FLAGSHIP' THEN '旗舰店'
        WHEN 'SPECIALTY' THEN '专卖店'
        WHEN 'FRANCHISE' THEN '专营店'
        ELSE '其他'
    END AS shop_type_name,
    CASE dsf.shop_status
        WHEN 'OPEN' THEN '营业中'
        WHEN 'CLOSED' THEN '已关闭'
        WHEN 'FROZEN' THEN '冻结'
        ELSE '其他'
    END AS shop_status_name,
    CASE
        WHEN dsf.open_time IS NOT NULL
        THEN (CURRENT_DATE - dsf.open_time::DATE)
        ELSE NULL
    END AS open_days,
    drf.region_name AS province_name,
    COALESCE(order_agg.total_order_cnt, 0) AS total_order_cnt,
    COALESCE(order_agg.total_sales_amount, 0) AS total_sales_amount,
    COALESCE(order_agg.total_buyer_cnt, 0) AS total_buyer_cnt,
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
