/* =====================================================
   ETL 转换脚本（纯 SELECT，DDL/INSERT/UT 由脚本处理）
   规则: R0001 - 用户画像宽表写入
   目标表: slusr.dwb_user_profile_f
   来源表:
     - ods.ods_user_basic_f (oub) 主表，粒度锚点：用户
     - dim.dim_user_level_d  (dul) LEFT JOIN ON level_id      一对一不发散
     - dim.dim_region_d      (drd) LEFT JOIN ON province_code=region_code 一对一不发散
     - dim.dim_user_source_d (dus) LEFT JOIN ON source_id     一对一不发散
   粒度: 无变化（一行=一个用户画像记录）
   写入方式: 全量 truncate
   说明: 以用户基础信息为主表，LEFT JOIN 三张维度表补充画像属性；
         字段以直取为主，少量字段做脱敏/代码翻译/时间提取加工。
   ===================================================== */
SELECT
    /* ---- ods.ods_user_basic_f (oub) ---- */
    oub.user_id AS user_id,
    COALESCE(oub.user_name, '') AS user_name,
    /* 手机号脱敏：保留前3后4，中间 ****（NULL→''，||遇NULL整体为NULL触发COALESCE） */
    COALESCE(LEFT(oub.user_phone, 3) || '****' || RIGHT(oub.user_phone, 4), '') AS user_phone_processed,
    COALESCE(oub.user_phone_masked, '') AS user_phone_masked,
    COALESCE(oub.email, '') AS email,
    /* 性别代码翻译：M→男、F→女、其余（含NULL）→未知 */
    CASE oub.gender
        WHEN 'M' THEN '男'
        WHEN 'F' THEN '女'
        ELSE '未知'
    END AS gender_processed,
    oub.birthday AS birthday,
    /* 年龄：当前年份 - 出生日期所在年份 */
    COALESCE(CAST(EXTRACT(YEAR FROM CURRENT_DATE) AS INT) - CAST(EXTRACT(YEAR FROM oub.birthday) AS INT), 0) AS age_processed,
    COALESCE(oub.id_card, '') AS id_card,
    /* 身份证脱敏：保留前6后4，中间 ********（输入取原始 id_card，避免对已脱敏值二次脱敏） */
    COALESCE(LEFT(oub.id_card, 6) || '********' || RIGHT(oub.id_card, 4), '') AS id_card_masked_processed,
    COALESCE(oub.real_name, '') AS real_name,
    COALESCE(oub.nick_name, '') AS nick_name,
    COALESCE(oub.avatar_url, '') AS avatar_url,
    COALESCE(oub.user_status, '') AS user_status,
    /* 用户状态翻译：ACTIVE→正常、INACTIVE→未激活、BANNED→封禁、其余→未知（按状态码翻译） */
    CASE oub.user_status
        WHEN 'ACTIVE' THEN '正常'
        WHEN 'INACTIVE' THEN '未激活'
        WHEN 'BANNED' THEN '封禁'
        ELSE '未知'
    END AS user_status_name_processed,
    oub.register_time AS register_time,
    /* 注册日期/小时/星期：取注册时间的对应部分 */
    CAST(oub.register_time AS DATE) AS register_date_processed,
    COALESCE(CAST(EXTRACT(HOUR FROM oub.register_time) AS INT), 0) AS register_hour_processed,
    COALESCE(CAST(EXTRACT(DOW FROM oub.register_time) AS INT), 0) AS register_weekday_processed,
    oub.last_login_time AS last_login_time,
    CAST(oub.last_login_time AS DATE) AS last_login_date_processed,
    COALESCE(oub.login_count, 0) AS login_count,
    COALESCE(oub.province_code, '') AS province_code,
    COALESCE(oub.province_name, '') AS province_name,
    COALESCE(oub.city_code, '') AS city_code,
    COALESCE(oub.city_name, '') AS city_name,
    COALESCE(oub.district_code, '') AS district_code,
    COALESCE(oub.district_name, '') AS district_name,
    COALESCE(oub.address, '') AS address,
    COALESCE(oub.zip_code, '') AS zip_code,
    COALESCE(oub.source_id, 0) AS source_id,
    COALESCE(oub.source_name, '') AS source_name,
    COALESCE(oub.source_type, '') AS source_type,
    COALESCE(oub.device_type, '') AS device_type,
    COALESCE(oub.os_type, '') AS os_type,
    COALESCE(oub.app_version, '') AS app_version,
    COALESCE(oub.ip_address, '') AS ip_address,
    COALESCE(oub.longitude, 0) AS longitude,
    COALESCE(oub.latitude, 0) AS latitude,
    COALESCE(oub.language, '') AS language,
    COALESCE(oub.timezone, '') AS timezone,
    COALESCE(oub.currency, '') AS currency,
    COALESCE(oub.vip_level, 0) AS vip_level,
    oub.vip_expire_time AS vip_expire_time,
    /* 是否VIP：VIP到期时间晚于当前时间判1，否则0 */
    CASE WHEN oub.vip_expire_time > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS is_vip_processed,
    COALESCE(oub.member_points, 0) AS member_points,
    COALESCE(oub.balance, 0) AS balance,
    COALESCE(oub.credit_score, 0) AS credit_score,
    COALESCE(oub.risk_level, '') AS risk_level,
    COALESCE(oub.verify_status, '') AS verify_status,
    /* ---- dim.dim_user_level_d (dul) ---- */
    COALESCE(dul.level_id, 0) AS level_id,
    COALESCE(dul.level_name, '') AS level_name,
    COALESCE(dul.level_code, '') AS level_code,
    COALESCE(dul.level_rank, 0) AS level_rank,
    COALESCE(dul.min_points, 0) AS min_points,
    COALESCE(dul.max_points, 0) AS max_points,
    COALESCE(dul.level_icon, '') AS level_icon,
    COALESCE(dul.level_color, '') AS level_color,
    COALESCE(dul.upgrade_points, 0) AS upgrade_points,
    COALESCE(dul.current_level_points, 0) AS current_level_points,
    COALESCE(dul.next_level_points, 0) AS next_level_points,
    /* 升级进度百分比：当前等级积分 / 升级所需积分 * 100（除零保护） */
    CASE
        WHEN COALESCE(dul.upgrade_points, 0) = 0 THEN 0
        ELSE COALESCE(dul.current_level_points, 0) * 100.0 / dul.upgrade_points
    END AS progress_percentage,
    COALESCE(dul.privilege_list, '') AS privilege_list,
    COALESCE(dul.discount_rate, 0) AS discount_rate,
    COALESCE(dul.points_rate, 0) AS points_rate,
    COALESCE(dul.free_shipping, 0) AS free_shipping,
    COALESCE(dul.exclusive_products, 0) AS exclusive_products,
    COALESCE(dul.priority_support, 0) AS priority_support,
    COALESCE(dul.birthday_bonus, 0) AS birthday_bonus,
    COALESCE(dul.monthly_coupon, 0) AS monthly_coupon,
    COALESCE(dul.annual_gift, 0) AS annual_gift,
    COALESCE(dul.vip_service, 0) AS vip_service,
    COALESCE(dul.invite_quota, 0) AS invite_quota,
    COALESCE(dul.max_orders_per_day, 0) AS max_orders_per_day,
    COALESCE(dul.max_return_days, 0) AS max_return_days,
    COALESCE(dul.level_benefits, '') AS level_benefits,
    dul.upgrade_time AS upgrade_time,
    dul.downgrade_time AS downgrade_time,
    COALESCE(dul.maintain_days, 0) AS maintain_days,
    COALESCE(dul.level_status, '') AS level_status,
    dul.create_time AS create_time,
    dul.update_time AS update_time,
    dul.valid_from AS valid_from,
    dul.valid_to AS valid_to,
    COALESCE(dul.is_active, 0) AS is_active,
    COALESCE(dul.level_tier, 0) AS level_tier,
    COALESCE(dul.level_group, '') AS level_group,
    COALESCE(dul.level_category, '') AS level_category,
    COALESCE(dul.points_required, 0) AS points_required,
    COALESCE(dul.orders_required, 0) AS orders_required,
    COALESCE(dul.amount_required, 0) AS amount_required,
    COALESCE(dul.days_required, 0) AS days_required,
    COALESCE(dul.growth_value, 0) AS growth_value,
    COALESCE(dul.experience_value, 0) AS experience_value,
    COALESCE(dul.contribution_value, 0) AS contribution_value,
    COALESCE(dul.activity_value, 0) AS activity_value,
    COALESCE(dul.loyalty_score, 0) AS loyalty_score,
    COALESCE(dul.engagement_score, 0) AS engagement_score,
    COALESCE(dul.satisfaction_score, 0) AS satisfaction_score,
    COALESCE(dul.retention_score, 0) AS retention_score,
    /* ---- dim.dim_region_d (drd) ---- */
    COALESCE(drd.region_id, 0) AS region_id,
    COALESCE(drd.region_code, '') AS region_code,
    COALESCE(drd.region_name, '') AS region_name,
    COALESCE(drd.parent_id, 0) AS parent_id,
    COALESCE(drd.region_level, 0) AS region_level,
    COALESCE(drd.region_path, '') AS region_path,
    COALESCE(drd.province_id, 0) AS province_id,
    COALESCE(drd.province_abbr, '') AS province_abbr,
    COALESCE(drd.city_id, 0) AS city_id,
    COALESCE(drd.city_abbr, '') AS city_abbr,
    COALESCE(drd.district_id, 0) AS district_id,
    COALESCE(drd.district_abbr, '') AS district_abbr,
    COALESCE(drd.street_id, 0) AS street_id,
    COALESCE(drd.street_code, '') AS street_code,
    COALESCE(drd.street_name, '') AS street_name,
    COALESCE(drd.center_longitude, 0) AS center_longitude,
    COALESCE(drd.center_latitude, 0) AS center_latitude,
    COALESCE(drd.area_size, 0) AS area_size,
    COALESCE(drd.population, 0) AS population,
    COALESCE(drd.gdp, 0) AS gdp,
    COALESCE(drd.gdp_per_capita, 0) AS gdp_per_capita,
    COALESCE(drd.climate_type, '') AS climate_type,
    COALESCE(drd.economy_level, '') AS economy_level,
    COALESCE(drd.development_level, '') AS development_level,
    COALESCE(drd.urban_rate, 0) AS urban_rate,
    COALESCE(drd.region_type, '') AS region_type,
    COALESCE(drd.is_coastal, 0) AS is_coastal,
    COALESCE(drd.is_border, 0) AS is_border,
    COALESCE(drd.is_capital, 0) AS is_capital,
    COALESCE(drd.is_special, 0) AS is_special,
    COALESCE(drd.postal_code_prefix, '') AS postal_code_prefix,
    COALESCE(drd.phone_area_code, '') AS phone_area_code,
    COALESCE(drd.car_plate_prefix, '') AS car_plate_prefix,
    COALESCE(drd.airport_code, '') AS airport_code,
    COALESCE(drd.railway_station_code, '') AS railway_station_code,
    COALESCE(drd.port_code, '') AS port_code,
    COALESCE(drd.weather_station_code, '') AS weather_station_code,
    COALESCE(drd.customs_code, '') AS customs_code,
    COALESCE(drd.statistical_code, '') AS statistical_code,
    COALESCE(drd.iso_code, '') AS iso_code,
    /* ---- dim.dim_user_source_d (dus) ---- */
    COALESCE(dus.source_code, '') AS source_code,
    COALESCE(dus.source_category, '') AS source_category,
    COALESCE(dus.channel_id, 0) AS channel_id,
    COALESCE(dus.channel_code, '') AS channel_code,
    COALESCE(dus.channel_name, '') AS channel_name,
    COALESCE(dus.channel_type, '') AS channel_type,
    COALESCE(dus.channel_category, '') AS channel_category,
    COALESCE(dus.campaign_id, 0) AS campaign_id,
    COALESCE(dus.campaign_code, '') AS campaign_code,
    COALESCE(dus.campaign_name, '') AS campaign_name,
    COALESCE(dus.campaign_type, '') AS campaign_type,
    COALESCE(dus.medium_id, 0) AS medium_id,
    COALESCE(dus.medium_code, '') AS medium_code,
    COALESCE(dus.medium_name, '') AS medium_name,
    COALESCE(dus.medium_type, '') AS medium_type,
    COALESCE(dus.term_id, 0) AS term_id,
    COALESCE(dus.term_keyword, '') AS term_keyword,
    COALESCE(dus.content_id, 0) AS content_id,
    COALESCE(dus.content_name, '') AS content_name,
    COALESCE(dus.referral_url, '') AS referral_url,
    COALESCE(dus.landing_page, '') AS landing_page,
    COALESCE(dus.utm_source, '') AS utm_source,
    COALESCE(dus.utm_medium, '') AS utm_medium,
    COALESCE(dus.utm_campaign, '') AS utm_campaign,
    COALESCE(dus.utm_term, '') AS utm_term,
    COALESCE(dus.utm_content, '') AS utm_content,
    COALESCE(dus.cost_per_acquisition, 0) AS cost_per_acquisition,
    COALESCE(dus.conversion_rate, 0) AS conversion_rate,
    COALESCE(dus.quality_score, 0) AS quality_score,
    COALESCE(dus.retention_rate_7d, 0) AS retention_rate_7d,
    COALESCE(dus.retention_rate_30d, 0) AS retention_rate_30d,
    COALESCE(dus.lifetime_value, 0) AS lifetime_value,
    COALESCE(dus.first_order_amount, 0) AS first_order_amount,
    COALESCE(dus.first_order_days, 0) AS first_order_days,
    COALESCE(dus.register_device, '') AS register_device,
    COALESCE(dus.register_os, '') AS register_os,
    COALESCE(dus.register_browser, '') AS register_browser,
    COALESCE(dus.register_network, '') AS register_network,
    COALESCE(dus.register_location, '') AS register_location,
    COALESCE(dus.attribution_model, '') AS attribution_model,
    COALESCE(dus.lookback_days, 0) AS lookback_days,
    COALESCE(dus.priority, 0) AS priority,
    COALESCE(dus.is_paid, 0) AS is_paid,
    /* ---- 审计字段 ---- */
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_user_basic_f oub
LEFT JOIN dim.dim_user_level_d dul
    ON oub.level_id = dul.level_id
    AND dul.del_flag = 'N'
LEFT JOIN dim.dim_region_d drd
    ON oub.province_code = drd.region_code
    AND drd.del_flag = 'N'
LEFT JOIN dim.dim_user_source_d dus
    ON oub.source_id = dus.source_id
    AND dus.del_flag = 'N'
WHERE oub.del_flag = 'N';
