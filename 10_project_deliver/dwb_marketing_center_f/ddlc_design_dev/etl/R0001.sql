/* =====================================================
   R0001: 订单指标预聚合
   目标表: slmar.dwb_marketing_center_order_mid_f (中间表)
   设计意图: 按 activity_id 预聚合订单指标(订单数/GMV/参与人数/优惠金额/新客占比),
            将 dwd_order_f 多行(每笔订单)收敛为一行(每个活动),
            防止主查询关联订单表时发散。
   粒度: 一行=一笔订单 → 一行=一个活动(按 activity_id 聚合)
   来源表:
     - sdord.dwd_order_f dof (订单事实表)
     - sdmar.dwd_activity_f daf (活动事实表, INNER JOIN on activity_id, 取活动时间窗口)
   ===================================================== */
WITH
/* CTE: 用户历史首单时间(扫描 dwd_order_f 全量, 按 user_id 取 MIN 下单时间),
       用于判定该用户是否为某活动期间的新用户 */
user_first_order AS (
    SELECT
        user_id,
        MIN(order_time) AS first_order_time
    FROM sdord.dwd_order_f
    WHERE del_flag = 'N'
    GROUP BY user_id
)

SELECT
    /* 业务主键/分组键: activity_id (也是分布键和下游 JOIN 关联键) */
    dof.activity_id AS activity_id,
    /* 活动订单数: 按 activity_id 计数活动下的订单行 */
    COUNT(1) AS order_cnt,
    /* 活动GMV: 按 activity_id 汇总活动下所有订单的 pay_amount */
    COALESCE(SUM(dof.pay_amount), 0) AS gmv_amount,
    /* 参与人数: 按 activity_id 对 user_id 去重计数 */
    COUNT(DISTINCT dof.user_id) AS participant_cnt,
    /* 活动优惠金额: 按 activity_id 汇总活动下所有订单的 discount_amount */
    COALESCE(SUM(dof.discount_amount), 0) AS total_discount_amount,
    /* 新客占比(%): 分子=首单时间落在活动[start_time,end_time]窗口内的用户产生的订单数,
       分母=活动总订单数(order_cnt), 比值×100; 分母为0时返回NULL */
    CAST(
        SUM(CASE WHEN ufo.first_order_time BETWEEN daf.start_time AND daf.end_time THEN 1 ELSE 0 END) * 100.0
            / NULLIF(COUNT(1), 0)
        AS NUMERIC(5,2)
    ) AS new_user_rate,
    /* 审计字段 */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_f dof
INNER JOIN sdmar.dwd_activity_f daf
    ON dof.activity_id = daf.activity_id
    AND daf.del_flag = 'N'
LEFT JOIN user_first_order ufo
    ON dof.user_id = ufo.user_id
WHERE dof.del_flag = 'N'
GROUP BY dof.activity_id, daf.start_time, daf.end_time;
