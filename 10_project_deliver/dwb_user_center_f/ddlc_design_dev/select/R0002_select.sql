/* R0002: 行为画像中间表（将用户行为事实表按用户聚合收口为用户粒度的行为画像，提供浏览/收藏/加购行为指标，支撑转化率派生计算） */
SELECT
    dub.user_id AS user_id,
    COALESCE(SUM(dub.pv_cnt), 0) AS total_pv_cnt,
    COALESCE(SUM(dub.collect_cnt), 0) AS total_collect_cnt,
    COALESCE(SUM(dub.cart_cnt), 0) AS total_cart_cnt,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdlog.dwd_user_behavior_f dub
GROUP BY dub.user_id;
