/* =====================================================
   ETL SELECT 脚本（仅 SELECT，DDL/INSERT/UT 由脚本处理）
   规则号: R0001
   规则名: 营销中心宽表写入
   目标表: slmar.dwb_marketing_center_f
   粒度: 一行=一个营销活动（activity_id 唯一，全量覆盖写入）
   来源表:
     - sdmar.dwd_activity_f (daf, 主表/粒度锚点)
     - dim.dim_activity_type_f (dat, 活动类型维度)
     - dim.dim_coupon_f (dcf, 优惠券维度)
     - sdord.dwd_order_f (dof, 在 CTE order_agg 内预聚合)
   生成说明:
     以 dwd_activity_f 为锚点，LEFT JOIN 活动类型/优惠券维度；
     订单明细经 CTE order_agg 按 activity_id 收敛后再 LEFT JOIN，
     避免一对多 fan-out；派生比率在主查询层用 NULLIF 防除零。
   ===================================================== */

-- ⚠ 待人工确认：新客判定字段，当前按 is_new_user='Y' 假设，无此字段则计 0
-- ⚠ 待人工确认：活动成本=优惠金额+满减金额+运营成本，后两项来源未定，暂按 0

WITH order_agg AS (
    /* CTE: 订单明细事实表按 activity_id 收敛，预聚合活动级订单指标
       （订单数 / GMV / 参与人数 / 优惠金额 / 新客订单数），
       避免 dwd_order_f 一对多直接 JOIN 导致活动行发散。 */
    SELECT
        dof.activity_id AS activity_id,
        COUNT(1) AS order_cnt,
        COALESCE(SUM(dof.pay_amount), 0) AS gmv_amount,
        COUNT(DISTINCT dof.user_id) AS participant_cnt,
        COALESCE(SUM(dof.discount_amount), 0) AS total_discount_amount,
        COUNT(*) FILTER (WHERE dof.is_new_user = 'Y') AS new_user_order_cnt
    FROM sdord.dwd_order_f dof
    WHERE dof.del_flag = 'N'
    GROUP BY dof.activity_id
)
SELECT
    daf.activity_id AS activity_id,
    COALESCE(daf.activity_name, '') AS activity_name,
    CASE daf.activity_type
        WHEN 'SECKILL' THEN '秒杀'
        WHEN 'GROUPBUY' THEN '团购'
        WHEN 'PRESALE' THEN '预售'
        WHEN 'FULL_REDUCE' THEN '满减'
        WHEN 'FULL_GIFT' THEN '满赠'
        ELSE '其他'
    END AS activity_type_name,
    COALESCE(dat.type_desc, '') AS activity_type_desc,
    CASE daf.activity_status
        WHEN 'DRAFT' THEN '草稿'
        WHEN 'PENDING' THEN '待开始'
        WHEN 'RUNNING' THEN '进行中'
        WHEN 'ENDED' THEN '已结束'
        ELSE '其他'
    END AS activity_status_name,
    daf.start_time AS start_time,
    daf.end_time AS end_time,
    /* 活动天数 = 结束时间与开始时间的天数差（DWS/GaussDB: date 相减得天数） */
    COALESCE((daf.end_time::date - daf.start_time::date), 0) AS activity_days,
    daf.create_time AS create_time,
    COALESCE(daf.min_amount, 0) AS min_amount,
    COALESCE(daf.discount_rate, 0) AS discount_rate,
    COALESCE(daf.max_discount, 0) AS max_discount,
    COALESCE(dcf.coupon_id, 0) AS coupon_id,
    COALESCE(dcf.coupon_name, '') AS coupon_name,
    CASE dcf.coupon_type
        WHEN 'FULL_REDUCE' THEN '满减券'
        WHEN 'DISCOUNT' THEN '折扣券'
        WHEN 'CASH' THEN '现金券'
        ELSE '其他'
    END AS coupon_type_name,
    COALESCE(dcf.total_qty, 0) AS coupon_total_qty,
    COALESCE(dcf.used_qty, 0) AS coupon_used_qty,
    /* 优惠券使用率 = 已使用量 / 发放总量 × 100；发放总量为 0 时 NULLIF 返回 NULL 避免除零 */
    dcf.used_qty * 100.0 / NULLIF(dcf.total_qty, 0) AS coupon_use_rate,
    COALESCE(order_agg.order_cnt, 0) AS order_cnt,
    COALESCE(order_agg.gmv_amount, 0) AS gmv_amount,
    COALESCE(order_agg.participant_cnt, 0) AS participant_cnt,
    COALESCE(order_agg.total_discount_amount, 0) AS total_discount_amount,
    /* 新客占比 = 新客订单数 / 总订单数 × 100；总订单数为 0 时返回 NULL 避免除零 */
    COALESCE(order_agg.new_user_order_cnt, 0) * 100.0
        / NULLIF(COALESCE(order_agg.order_cnt, 0), 0) AS new_user_rate,
    /* 人均消费 = GMV / 参与人数；参与人数为 0 时返回 NULL 避免除零 */
    COALESCE(order_agg.gmv_amount, 0)
        / NULLIF(COALESCE(order_agg.participant_cnt, 0), 0) AS avg_order_amount,
    /* 活动 ROI = (GMV − 活动成本) / 活动成本 × 100；
       活动成本 = 优惠金额 + 满减金额(0) + 运营成本(0)；活动成本为 0 时返回 NULL 避免除零 */
    (COALESCE(order_agg.gmv_amount, 0) - COALESCE(order_agg.total_discount_amount, 0)) * 100.0
        / NULLIF(COALESCE(order_agg.total_discount_amount, 0), 0) AS activity_roi,
    /* 审计字段 */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdmar.dwd_activity_f daf
LEFT JOIN dim.dim_activity_type_f dat
    ON daf.activity_type = dat.type_code
    AND dat.del_flag = 'N'
LEFT JOIN dim.dim_coupon_f dcf
    ON daf.activity_id = dcf.activity_id
    AND dcf.del_flag = 'N'
LEFT JOIN order_agg
    ON daf.activity_id = order_agg.activity_id
WHERE daf.del_flag = 'N';
