/* =====================================================
   R0003: 营销画像中间表（营销域用户粒度收口）
   目标表: slusr.dwb_user_marketing_tmp
   设计意图: 将优惠券使用、退款、购物车三张事实表各自按用户聚合后
             合并为用户粒度的营销画像，收口营销域指标
   来源表:
     - sdmar.dwd_coupon_use_f (dcu)   优惠券使用事实
     - sdref.dwd_refund_f     (drf9)  退款事实
     - sdlog.dwd_cart_f       (dcf)   购物车事实
   粒度: 明细(优惠券/退款/购物车) → 用户(一行一用户)
   关联安全: 三张源表各自 GROUP BY user_id 收敛后再合并，
             保证 user_id 唯一不发散
   合并策略: FULL OUTER JOIN + COALESCE(user_id)，
             保留任意一张源表出现的用户，不丢维度
   ===================================================== */
SELECT
    /* 粒度键 user_id：三源 FULL OUTER JOIN 后取首个非空 */
    COALESCE(dcu.user_id, drf9.user_id, dcf.user_id) user_id,
    COALESCE(dcu.coupon_used_cnt, 0)            AS coupon_used_cnt,
    COALESCE(dcu.coupon_total_amount, 0)        AS coupon_total_amount,
    COALESCE(drf9.refund_cnt, 0)                AS refund_cnt,
    COALESCE(dcf.cart_product_cnt, 0)           AS cart_product_cnt,
    COALESCE(dcf.cart_total_amount, 0)          AS cart_total_amount,
    'N'                                         AS del_flag,
    '${P_CYCLE_ID}'                             AS crt_cycle_id,
    '${P_CYCLE_ID}'                             AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                           AS dw_last_update_date
FROM (
    /* 优惠券使用子聚合：按 user_id 收敛 */
    SELECT
        user_id,
        COUNT(1)                            AS coupon_used_cnt,
        COALESCE(SUM(coupon_amount), 0)     AS coupon_total_amount
    FROM sdmar.dwd_coupon_use_f
    WHERE COALESCE(del_flag, 'N') = 'N'
    GROUP BY user_id
) dcu
FULL OUTER JOIN (
    /* 退款子聚合：按 user_id 收敛 */
    SELECT
        user_id,
        COUNT(1) AS refund_cnt
    FROM sdref.dwd_refund_f
    WHERE COALESCE(del_flag, 'N') = 'N'
    GROUP BY user_id
) drf9
    ON dcu.user_id = drf9.user_id
FULL OUTER JOIN (
    /* 购物车子聚合：按 user_id 收敛（仅未删除记录） */
    SELECT
        user_id,
        COUNT(1)                                    AS cart_product_cnt,
        COALESCE(SUM(product_qty * unit_price), 0)  AS cart_total_amount
    FROM sdlog.dwd_cart_f
    WHERE del_flag = 'N'
    GROUP BY user_id
) dcf
    ON COALESCE(dcu.user_id, drf9.user_id) = dcf.user_id;
