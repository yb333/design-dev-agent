/* =====================================================
   R0001: 用户画像宽表全量装载
   目标表: slusr.dwb_user_profile_f
   主表: ods.ods_user_basic_f (oub) 全量
   关联:
     - dim.dim_user_level_d (dul): SCD2 收敛,取当前有效行
       (is_active=1 且 valid_from<=当前时间<valid_to),保证 level_id 唯一
     - dim.dim_region_d (drd): 限定 region_level=1(省份层级)收敛,
       保证 region_code 唯一
     - dim.dim_user_source_d (dus): source_id 唯一,直接 LEFT JOIN
   粒度: 无变化 (用户 -> 用户),无聚合
   说明: 多个 _processed 字段 TS 的 source_fields 与 design_logic 不一致,
        按 skill 约定以 design_logic 口径为准翻译(详见回报)。
   ===================================================== */
SELECT
    /* ---------- 主表 ods_user_basic_f 基础属性 ---------- */
    oub.user_id AS user_id,                                                       /* 用户ID */
    COALESCE(oub.user_name, '') AS user_name,                                     /* 用户姓名 */
    COALESCE(LEFT(oub.user_phone, 3) || '****' || RIGHT(oub.user_phone, 4), '') AS user_phone_processed,  /* 手机号(脱敏:前3+****+后4) */
    COALESCE(oub.user_phone_masked, '') AS user_phone_masked,                     /* 手机号(脱敏) */
    COALESCE(oub.email, '') AS email,                                             /* 电子邮箱 */
    CASE oub.gender
        WHEN 'M' THEN '男'
        WHEN 'F' THEN '女'
        ELSE '未知'
    END AS gender_processed,                                                      /* 性别(M男/F女/其它未知) */
    oub.birthday AS birthday,                                                     /* 出生日期 */
    COALESCE((DATE_PART('YEAR', CURRENT_DATE) - DATE_PART('YEAR', oub.birthday))::INT, 0) AS age_processed,  /* 年龄(当前年-出生年) */
    COALESCE(oub.id_card, '') AS id_card,                                         /* 身份证号 */
    COALESCE(LEFT(oub.id_card_masked, 6) || '********' || RIGHT(oub.id_card_masked, 4), '') AS id_card_masked_processed,  /* 身份证号(脱敏:前6+********+后4) */
    COALESCE(oub.real_name, '') AS real_name,                                     /* 真实姓名 */
    COALESCE(oub.nick_name, '') AS nick_name,                                     /* 昵称 */
    COALESCE(oub.avatar_url, '') AS avatar_url,                                   /* 头像URL */
    COALESCE(oub.user_status, '') AS user_status,                                 /* 用户状态 */
    CASE oub.user_status
        WHEN 'ACTIVE' THEN '正常'
        WHEN 'INACTIVE' THEN '未激活'
        WHEN 'BANNED' THEN '封禁'
        ELSE '未知'
    END AS user_status_name_processed,                                            /* 用户状态名称(ACTIVE正常/INACTIVE未激活/BANNED封禁/其它未知) */
    oub.register_time AS register_time,                                           /* 注册时间 */
    oub.register_time::DATE AS register_date_processed,                           /* 注册日期(取注册时间日期部分) */
    COALESCE(DATE_PART('HOUR', oub.register_time)::INT, 0) AS register_hour_processed,  /* 注册小时(0~23) */
    COALESCE(DATE_PART('ISODOW', oub.register_time)::INT, 0) AS register_weekday_processed,  /* 注册星期(1周一~7周日) */
    oub.last_login_time AS last_login_time,                                       /* 最后登录时间 */
    oub.last_login_time::DATE AS last_login_date_processed,                       /* 最后登录日期(取最后登录时间日期部分) */
    COALESCE(oub.login_count, 0) AS login_count,                                  /* 登录次数 */
    COALESCE(oub.province_code, '') AS province_code,                             /* 省份代码 */
    COALESCE(oub.province_name, '') AS province_name,                             /* 省份名称 */
    COALESCE(oub.city_code, '') AS city_code,                                     /* 城市代码 */
    COALESCE(oub.city_name, '') AS city_name,                                     /* 城市名称 */
    COALESCE(oub.district_code, '') AS district_code,                             /* 区县代码 */
    COALESCE(oub.district_name, '') AS district_name,                             /* 区县名称 */
    COALESCE(oub.address, '') AS address,                                         /* 详细地址 */
    COALESCE(oub.zip_code, '') AS zip_code,                                       /* 邮政编码 */
    COALESCE(oub.source_id, 0) AS source_id,                                      /* 来源渠道ID */
    COALESCE(oub.source_name, '') AS source_name,                                 /* 来源渠道名称 */
    COALESCE(oub.source_type, '') AS source_type,                                 /* 来源类型 */
    COALESCE(oub.device_type, '') AS device_type,                                 /* 设备类型 */
    COALESCE(oub.os_type, '') AS os_type,                                         /* 操作系统 */
    COALESCE(oub.app_version, '') AS app_version,                                 /* APP版本 */
    COALESCE(oub.ip_address, '') AS ip_address,                                   /* IP地址 */
    COALESCE(oub.longitude, 0) AS longitude,                                      /* 经度 */
    COALESCE(oub.latitude, 0) AS latitude,                                        /* 纬度 */
    COALESCE(oub.language, '') AS language,                                       /* 语言 */
    COALESCE(oub.timezone, '') AS timezone,                                       /* 时区 */
    COALESCE(oub.currency, '') AS currency,                                       /* 货币 */
    COALESCE(oub.vip_level, 0) AS vip_level,                                      /* VIP等级 */
    oub.vip_expire_time AS vip_expire_time,                                       /* VIP到期时间 */
    CASE WHEN oub.vip_expire_time > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS is_vip_processed,  /* 是否VIP(到期时间晚于当前时间取1,否则0) */
    COALESCE(oub.member_points, 0) AS member_points,                              /* 会员积分 */
    COALESCE(oub.balance, 0) AS balance,                                          /* 账户余额 */
    COALESCE(oub.credit_score, 0) AS credit_score,                                /* 信用分 */
    COALESCE(oub.risk_level, '') AS risk_level,                                   /* 风险等级 */
    COALESCE(oub.verify_status, '') AS verify_status,                             /* 认证状态 */

    /* ---------- dim_user_level_d 等级维度(SCD2 取当前有效行) ---------- */
    dul.level_id AS level_id,                                                     /* 等级ID */
    COALESCE(dul.level_name, '') AS level_name,                                   /* 等级名称 */
    COALESCE(dul.level_code, '') AS level_code,                                   /* 等级代码 */
    COALESCE(dul.level_rank, 0) AS level_rank,                                    /* 等级排序 */
    COALESCE(dul.min_points, 0) AS min_points,                                    /* 最小积分 */
    COALESCE(dul.max_points, 0) AS max_points,                                    /* 最大积分 */
    COALESCE(dul.level_icon, '') AS level_icon,                                   /* 等级图标 */
    COALESCE(dul.level_color, '') AS level_color,                                 /* 等级颜色 */
    COALESCE(dul.upgrade_points, 0) AS upgrade_points,                            /* 升级所需积分 */
    COALESCE(dul.current_level_points, 0) AS current_level_points,                /* 当前等级积分 */
    COALESCE(dul.next_level_points, 0) AS next_level_points,                      /* 下一等级积分 */
    CASE
        WHEN COALESCE(dul.upgrade_points, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(dul.current_level_points, 0)::NUMERIC * 100.0 / dul.upgrade_points, 2)
    END AS progress_percentage,                                                   /* 升级进度百分比(当前等级积分/升级所需积分*100,除0保护) */
    COALESCE(dul.privilege_list, '') AS privilege_list,                           /* 权限列表 */
    COALESCE(dul.discount_rate, 0) AS discount_rate,                              /* 折扣率 */
    COALESCE(dul.points_rate, 0) AS points_rate,                                  /* 积分倍率 */
    COALESCE(dul.free_shipping, 0) AS free_shipping,                              /* 免费配送 */
    COALESCE(dul.exclusive_products, 0) AS exclusive_products,                    /* 专属商品 */
    COALESCE(dul.priority_support, 0) AS priority_support,                        /* 优先客服 */
    COALESCE(dul.birthday_bonus, 0) AS birthday_bonus,                            /* 生日礼金 */
    COALESCE(dul.monthly_coupon, 0) AS monthly_coupon,                            /* 月度优惠券 */
    COALESCE(dul.annual_gift, 0) AS annual_gift,                                  /* 年度礼品 */
    COALESCE(dul.vip_service, 0) AS vip_service,                                  /* VIP服务 */
    COALESCE(dul.invite_quota, 0) AS invite_quota,                                /* 邀请名额 */
    COALESCE(dul.max_orders_per_day, 0) AS max_orders_per_day,                    /* 每日最大订单数 */
    COALESCE(dul.max_return_days, 0) AS max_return_days,                          /* 最大退货天数 */
    COALESCE(dul.level_benefits, '') AS level_benefits,                           /* 等级权益 */
    dul.upgrade_time AS upgrade_time,                                             /* 升级时间 */
    dul.downgrade_time AS downgrade_time,                                         /* 降级时间 */
    COALESCE(dul.maintain_days, 0) AS maintain_days,                              /* 维持天数 */
    COALESCE(dul.level_status, '') AS level_status,                               /* 等级状态 */
    dul.create_time AS create_time,                                               /* 创建时间 */
    dul.update_time AS update_time,                                               /* 更新时间 */
    dul.valid_from AS valid_from,                                                 /* 生效开始时间 */
    dul.valid_to AS valid_to,                                                     /* 生效结束时间 */
    COALESCE(dul.is_active, 0) AS is_active,                                      /* 是否激活 */
    COALESCE(dul.level_tier, 0) AS level_tier,                                    /* 等级层级 */
    COALESCE(dul.level_group, '') AS level_group,                                 /* 等级分组 */
    COALESCE(dul.level_category, '') AS level_category,                           /* 等级分类 */
    COALESCE(dul.points_required, 0) AS points_required,                          /* 所需积分 */
    COALESCE(dul.orders_required, 0) AS orders_required,                          /* 所需订单数 */
    COALESCE(dul.amount_required, 0) AS amount_required,                          /* 所需金额 */
    COALESCE(dul.days_required, 0) AS days_required,                              /* 所需天数 */
    COALESCE(dul.growth_value, 0) AS growth_value,                                /* 成长值 */
    COALESCE(dul.experience_value, 0) AS experience_value,                        /* 经验值 */
    COALESCE(dul.contribution_value, 0) AS contribution_value,                    /* 贡献值 */
    COALESCE(dul.activity_value, 0) AS activity_value,                            /* 活跃值 */
    COALESCE(dul.loyalty_score, 0) AS loyalty_score,                              /* 忠诚度分数 */
    COALESCE(dul.engagement_score, 0) AS engagement_score,                        /* 参与度分数 */
    COALESCE(dul.satisfaction_score, 0) AS satisfaction_score,                    /* 满意度分数 */
    COALESCE(dul.retention_score, 0) AS retention_score,                          /* 留存率分数 */

    /* ---------- dim_region_d 地区维度(限定 region_level=1 省份层级) ---------- */
    COALESCE(drd.region_id, 0) AS region_id,                                      /* 地区ID */
    COALESCE(drd.region_code, '') AS region_code,                                 /* 地区代码 */
    COALESCE(drd.region_name, '') AS region_name,                                 /* 地区名称 */
    COALESCE(drd.parent_id, 0) AS parent_id,                                      /* 父级ID */
    COALESCE(drd.region_level, 0) AS region_level,                                /* 地区层级 */
    COALESCE(drd.region_path, '') AS region_path,                                 /* 地区路径 */
    COALESCE(drd.province_id, 0) AS province_id,                                  /* 省份ID */
    COALESCE(drd.province_abbr, '') AS province_abbr,                             /* 省份简称 */
    COALESCE(drd.city_id, 0) AS city_id,                                          /* 城市ID */
    COALESCE(drd.city_abbr, '') AS city_abbr,                                     /* 城市简称 */
    COALESCE(drd.district_id, 0) AS district_id,                                  /* 区县ID */
    COALESCE(drd.district_abbr, '') AS district_abbr,                             /* 区县简称 */
    COALESCE(drd.street_id, 0) AS street_id,                                      /* 街道ID */
    COALESCE(drd.street_code, '') AS street_code,                                 /* 街道代码 */
    COALESCE(drd.street_name, '') AS street_name,                                 /* 街道名称 */
    COALESCE(drd.center_longitude, 0) AS center_longitude,                        /* 中心经度 */
    COALESCE(drd.center_latitude, 0) AS center_latitude,                          /* 中心纬度 */
    COALESCE(drd.area_size, 0) AS area_size,                                      /* 区域面积 */
    COALESCE(drd.population, 0) AS population,                                    /* 人口数量 */
    COALESCE(drd.gdp, 0) AS gdp,                                                  /* GDP */
    COALESCE(drd.gdp_per_capita, 0) AS gdp_per_capita,                            /* 人均GDP */
    COALESCE(drd.climate_type, '') AS climate_type,                               /* 气候类型 */
    COALESCE(drd.economy_level, '') AS economy_level,                             /* 经济水平 */
    COALESCE(drd.development_level, '') AS development_level,                     /* 发展水平 */
    COALESCE(drd.urban_rate, 0) AS urban_rate,                                    /* 城镇化率 */
    COALESCE(drd.region_type, '') AS region_type,                                 /* 地区类型 */
    COALESCE(drd.is_coastal, 0) AS is_coastal,                                    /* 是否沿海 */
    COALESCE(drd.is_border, 0) AS is_border,                                      /* 是否边境 */
    COALESCE(drd.is_capital, 0) AS is_capital,                                    /* 是否省会 */
    COALESCE(drd.is_special, 0) AS is_special,                                    /* 是否特区 */
    COALESCE(drd.postal_code_prefix, '') AS postal_code_prefix,                   /* 邮编前缀 */
    COALESCE(drd.phone_area_code, '') AS phone_area_code,                         /* 电话区号 */
    COALESCE(drd.car_plate_prefix, '') AS car_plate_prefix,                       /* 车牌前缀 */
    COALESCE(drd.airport_code, '') AS airport_code,                               /* 机场代码 */
    COALESCE(drd.railway_station_code, '') AS railway_station_code,               /* 火车站代码 */
    COALESCE(drd.port_code, '') AS port_code,                                     /* 港口代码 */
    COALESCE(drd.weather_station_code, '') AS weather_station_code,               /* 气象站代码 */
    COALESCE(drd.customs_code, '') AS customs_code,                               /* 海关代码 */
    COALESCE(drd.statistical_code, '') AS statistical_code,                       /* 统计代码 */
    COALESCE(drd.iso_code, '') AS iso_code,                                       /* ISO代码 */

    /* ---------- dim_user_source_d 来源维度(source_id 唯一,直接关联) ---------- */
    COALESCE(dus.source_code, '') AS source_code,                                 /* 来源代码 */
    COALESCE(dus.source_category, '') AS source_category,                         /* 来源分类 */
    COALESCE(dus.channel_id, 0) AS channel_id,                                    /* 渠道ID */
    COALESCE(dus.channel_code, '') AS channel_code,                               /* 渠道代码 */
    COALESCE(dus.channel_name, '') AS channel_name,                               /* 渠道名称 */
    COALESCE(dus.channel_type, '') AS channel_type,                               /* 渠道类型 */
    COALESCE(dus.channel_category, '') AS channel_category,                       /* 渠道分类 */
    COALESCE(dus.campaign_id, 0) AS campaign_id,                                  /* 活动ID */
    COALESCE(dus.campaign_code, '') AS campaign_code,                             /* 活动代码 */
    COALESCE(dus.campaign_name, '') AS campaign_name,                             /* 活动名称 */
    COALESCE(dus.campaign_type, '') AS campaign_type,                             /* 活动类型 */
    COALESCE(dus.medium_id, 0) AS medium_id,                                      /* 媒介ID */
    COALESCE(dus.medium_code, '') AS medium_code,                                 /* 媒介代码 */
    COALESCE(dus.medium_name, '') AS medium_name,                                 /* 媒介名称 */
    COALESCE(dus.medium_type, '') AS medium_type,                                 /* 媒介类型 */
    COALESCE(dus.term_id, 0) AS term_id,                                          /* 搜索词ID */
    COALESCE(dus.term_keyword, '') AS term_keyword,                               /* 搜索关键词 */
    COALESCE(dus.content_id, 0) AS content_id,                                    /* 内容ID */
    COALESCE(dus.content_name, '') AS content_name,                               /* 内容名称 */
    COALESCE(dus.referral_url, '') AS referral_url,                               /* 来源URL */
    COALESCE(dus.landing_page, '') AS landing_page,                               /* 落地页 */
    COALESCE(dus.utm_source, '') AS utm_source,                                   /* UTM来源 */
    COALESCE(dus.utm_medium, '') AS utm_medium,                                   /* UTM媒介 */
    COALESCE(dus.utm_campaign, '') AS utm_campaign,                               /* UTM活动 */
    COALESCE(dus.utm_term, '') AS utm_term,                                       /* UTM关键词 */
    COALESCE(dus.utm_content, '') AS utm_content,                                 /* UTM内容 */
    COALESCE(dus.cost_per_acquisition, 0) AS cost_per_acquisition,                /* 获客成本 */
    COALESCE(dus.conversion_rate, 0) AS conversion_rate,                          /* 转化率 */
    COALESCE(dus.quality_score, 0) AS quality_score,                              /* 质量分数 */
    COALESCE(dus.retention_rate_7d, 0) AS retention_rate_7d,                      /* 7日留存率 */
    COALESCE(dus.retention_rate_30d, 0) AS retention_rate_30d,                    /* 30日留存率 */
    COALESCE(dus.lifetime_value, 0) AS lifetime_value,                            /* 生命周期价值 */
    COALESCE(dus.first_order_amount, 0) AS first_order_amount,                    /* 首单金额 */
    COALESCE(dus.first_order_days, 0) AS first_order_days,                        /* 首单天数 */
    COALESCE(dus.register_device, '') AS register_device,                         /* 注册设备 */
    COALESCE(dus.register_os, '') AS register_os,                                 /* 注册系统 */
    COALESCE(dus.register_browser, '') AS register_browser,                       /* 注册浏览器 */
    COALESCE(dus.register_network, '') AS register_network,                       /* 注册网络 */
    COALESCE(dus.register_location, '') AS register_location,                     /* 注册地点 */
    COALESCE(dus.attribution_model, '') AS attribution_model,                     /* 归因模型 */
    COALESCE(dus.lookback_days, 0) AS lookback_days,                              /* 回溯天数 */
    COALESCE(dus.priority, 0) AS priority,                                        /* 优先级 */
    COALESCE(dus.is_paid, 0) AS is_paid,                                          /* 是否付费 */

    /* ---------- 审计字段 ---------- */
    'N' AS del_flag,                                                              /* 删除标识 */
    '${P_CYCLE_ID}' AS crt_cycle_id,                                              /* 创建批次ID */
    '${P_CYCLE_ID}' AS last_upd_cycle_id,                                         /* 最后更新批次ID */
    CURRENT_TIMESTAMP AS dw_last_update_date                                      /* 数仓最后更新时间 */
FROM ods.ods_user_basic_f oub
/* dul: SCD2 收敛,取当前有效行(is_active=1 且生效期内),保证每个 level_id 唯一 */
LEFT JOIN (
    SELECT
        level_id, level_name, level_code, level_rank,
        min_points, max_points, level_icon, level_color,
        upgrade_points, current_level_points, next_level_points,
        privilege_list, discount_rate, points_rate,
        free_shipping, exclusive_products, priority_support,
        birthday_bonus, monthly_coupon, annual_gift, vip_service,
        invite_quota, max_orders_per_day, max_return_days,
        level_benefits, upgrade_time, downgrade_time, maintain_days,
        level_status, create_time, update_time,
        valid_from, valid_to, is_active, level_tier, level_group, level_category,
        points_required, orders_required, amount_required, days_required,
        growth_value, experience_value, contribution_value, activity_value,
        loyalty_score, engagement_score, satisfaction_score, retention_score
    FROM dim.dim_user_level_d
    WHERE del_flag = 'N'
      AND is_active = 1
      AND valid_from <= CURRENT_TIMESTAMP
      AND (valid_to IS NULL OR valid_to > CURRENT_TIMESTAMP)
) dul ON oub.level_id = dul.level_id
/* drd: 按地区层级收敛,限定 region_level=1(省份层级)保证 region_code 唯一 */
LEFT JOIN (
    SELECT
        region_id, region_code, region_name, parent_id, region_level,
        region_path, province_id, province_abbr, city_id, city_abbr,
        district_id, district_abbr, street_id, street_code, street_name,
        center_longitude, center_latitude, area_size, population,
        gdp, gdp_per_capita, climate_type, economy_level, development_level,
        urban_rate, region_type, is_coastal, is_border, is_capital, is_special,
        postal_code_prefix, phone_area_code, car_plate_prefix, airport_code,
        railway_station_code, port_code, weather_station_code, customs_code,
        statistical_code, iso_code
    FROM dim.dim_region_d
    WHERE del_flag = 'N'
      AND region_level = 1
) drd ON oub.province_code = drd.region_code
/* dus: source_id 唯一,直接 LEFT JOIN */
LEFT JOIN dim.dim_user_source_d dus
    ON oub.source_id = dus.source_id
   AND dus.del_flag = 'N'
WHERE oub.del_flag = 'N';
