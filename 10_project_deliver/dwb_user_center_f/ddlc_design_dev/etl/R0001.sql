/* =====================================================
   R0001: 用户基础属性中间表（以 dim_user_f 为主表，LEFT JOIN 等级/地区/来源维度，
          产出用户基础属性宽表，供最终装配规则引用。粒度不变：一行一用户。）
   目标表: slusr.dwb_user_center_tmp1
   来源表:
     - dim.dim_user_f         duf       (主表，用户维度)
     - dim.dim_user_level_f   dul       (等级维度，level_id 唯一)
     - dim.dim_region_f       drf       (地区维度-省份，region_code 唯一)
     - dim.dim_region_f       drf_city  (地区维度-城市，同表二次关联取城市名)
     - dim.dim_user_source_f  dus       (来源维度，source_id 唯一)
   ===================================================== */
SELECT
    duf.user_id                                                      AS user_id,
    duf.user_name                                                    AS user_name,
    /* 手机号脱敏：前3 + **** + 后4；NULL 或长度不足(<7) 时返回 NULL */
    CASE
        WHEN duf.user_phone IS NULL OR LENGTH(duf.user_phone) < 7
            THEN NULL
        ELSE CONCAT(LEFT(duf.user_phone, 3), '****', RIGHT(duf.user_phone, 4))
    END                                                              AS user_phone_masked,
    /* 性别代码转中文 */
    CASE duf.gender
        WHEN 'M' THEN '男'
        WHEN 'F' THEN '女'
        ELSE '未知'
    END                                                              AS gender_name,
    duf.birthday                                                     AS birthday,
    /* 年龄 = 当前年份 - 出生年份；birthday 为 NULL 时结果为 NULL */
    CASE
        WHEN duf.birthday IS NULL
            THEN NULL
        ELSE (EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM duf.birthday))::INT
    END                                                              AS age,
    duf.register_time                                                AS register_time,
    /* 注册天数 = 当前日期 - 注册日期；register_time 为 NULL 时结果为 NULL */
    CASE
        WHEN duf.register_time IS NULL
            THEN NULL
        ELSE (CURRENT_DATE - duf.register_time::DATE)
    END                                                              AS register_days,
    duf.last_login_time                                              AS last_login_time,
    duf.level_id                                                     AS level_id,
    COALESCE(dul.level_name, '')                                     AS level_name,
    COALESCE(dul.min_points, 0)                                      AS level_min_points,
    duf.province_code                                                AS province_code,
    COALESCE(drf.region_name, '')                                    AS province_name,
    duf.city_code                                                    AS city_code,
    /* 城市名称：通过 city_code 二次关联 dim_region_f 获取 */
    COALESCE(drf_city.region_name, '')                               AS city_name,
    COALESCE(dus.source_name, '')                                    AS source_name,
    duf.member_points                                                AS member_points,
    duf.member_balance                                               AS member_balance,
    /* 用户状态代码转中文 */
    CASE duf.user_status
        WHEN 'ACTIVE'   THEN '正常'
        WHEN 'INACTIVE' THEN '未激活'
        WHEN 'FROZEN'   THEN '冻结'
        ELSE '其他'
    END                                                              AS user_status_name,
    /* 审计字段（标准 4 个） */
    'N'                                                              AS del_flag,
    '${P_CYCLE_ID}'                                                  AS crt_cycle_id,
    '${P_CYCLE_ID}'                                                  AS last_upd_cycle_id,
    CURRENT_TIMESTAMP                                                AS dw_last_update_date
FROM dim.dim_user_f duf
LEFT JOIN dim.dim_user_level_f dul
    ON duf.level_id = dul.level_id
    AND dul.del_flag = 'N'
LEFT JOIN dim.dim_region_f drf
    ON duf.province_code = drf.region_code
    AND drf.del_flag = 'N'
LEFT JOIN dim.dim_region_f drf_city
    ON duf.city_code = drf_city.region_code
    AND drf_city.del_flag = 'N'
LEFT JOIN dim.dim_user_source_f dus
    ON duf.source_id = dus.source_id
    AND dus.del_flag = 'N'
WHERE duf.del_flag = 'N';
