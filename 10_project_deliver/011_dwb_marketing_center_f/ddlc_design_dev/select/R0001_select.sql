/* =====================================================
   R0001: 活动订单指标中间表
   目标表: slmar.dwb_marketing_order_tmp
   源表:   sdord.dwd_order_f (dof)
   设计意图: 将订单明细事实表按 activity_id 聚合收口到活动粒度，
             产出订单域核心指标（订单数/GMV/参与人数/优惠金额/新客占比），
             为最终宽表（R0002）提供订单指标输入。
   粒度变化: 订单明细（多行）→ 活动（一行），GROUP BY activity_id
   过滤口径: order_status NOT IN ('CANCELLED','DELETED')，仅计入有效订单
   ===================================================== */

/* ⚠️ new_user_rate 语义待人工确认（项目红线：语义判断不自主，coder 不拍板口径）
   -----------------------------------------------------------------------
   design_logic 原口径:
     "活动期间新用户订单数 / 总订单数 × 100"
     "新用户 = 用户全表首次下单时间落在【活动起止时间】(start_time~end_time) 内"
   -----------------------------------------------------------------------
   实现障碍:
     R0001 源表 dwd_order_f 仅含订单明细，不含活动起止时间(start_time/end_time)，
     无法按原口径严格判定"新用户"。
   -----------------------------------------------------------------------
   本规则采用的【订单表内自洽近似口径】(可执行实现，需人工确认后定案):
     1. 取每个用户在全表有效订单中的【首单活动】(最早有效订单所在的 activity_id)；
     2. 若某用户的首单活动 == 当前活动，则该用户在此活动产生的所有订单计为"新客订单"；
     3. new_user_rate = 新客订单数 / 活动总有效订单数 × 100，分母为 0 返回 NULL。
   -----------------------------------------------------------------------
   字段假设(待确认):
     - 首单判定排序字段: create_time（订单创建时间）。若源表实际字段名不同需调整。
     - 首单时间兜底: COALESCE(create_time, pay_time)。
   -----------------------------------------------------------------------
   若需严格按活动起止时间判定新客，应在 R0002 关联活动维表后重新计算此字段。
*/
SELECT
    dof.activity_id AS activity_id,
    COUNT(1) AS order_cnt,
    COALESCE(SUM(dof.pay_amount), 0) AS gmv_amount,
    COUNT(DISTINCT dof.user_id) AS participant_cnt,
    COALESCE(SUM(dof.discount_amount), 0) AS total_discount_amount,
    CASE
        WHEN COUNT(1) = 0 THEN NULL
        ELSE ROUND(
            COUNT(
                CASE WHEN ufa._first_activity_id IS NOT NULL
                      AND ufa._first_activity_id = dof.activity_id
                     THEN 1 END
            ) * 100.0 / COUNT(1),
            2
        )
    END AS new_user_rate,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_f dof
LEFT JOIN (
    /* 每个有效订单用户的全表首单活动（rn=1 即该用户最早有效订单所在活动） */
    SELECT
        _user_id,
        _first_activity_id
    FROM (
        SELECT
            user_id AS _user_id,
            activity_id AS _first_activity_id,
            ROW_NUMBER() OVER (
                PARTITION BY user_id
                ORDER BY COALESCE(create_time, pay_time) ASC
            ) AS _rn
        FROM sdord.dwd_order_f
        WHERE order_status NOT IN ('CANCELLED', 'DELETED')
          AND user_id IS NOT NULL
    ) _x
    WHERE _rn = 1
) ufa ON dof.user_id = ufa._user_id
WHERE dof.order_status NOT IN ('CANCELLED', 'DELETED')
GROUP BY dof.activity_id;
