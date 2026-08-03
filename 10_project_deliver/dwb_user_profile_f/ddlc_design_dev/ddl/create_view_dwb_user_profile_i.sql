/* I视图: slusr.dwb_user_profile_i（用户画像宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slusr.dwb_user_profile_i AS
SELECT
    user_id,
    user_name,
    user_phone_processed,
    user_phone_masked,
    email,
    gender_processed,
    birthday,
    age_processed,
    id_card,
    id_card_masked_processed,
    real_name,
    nick_name,
    avatar_url,
    user_status,
    user_status_name_processed,
    register_time,
    register_date_processed,
    register_hour_processed,
    register_weekday_processed,
    last_login_time,
    last_login_date_processed,
    login_count,
    province_code,
    province_name,
    city_code,
    city_name,
    district_code,
    district_name,
    address,
    zip_code,
    source_id,
    source_name,
    source_type,
    device_type,
    os_type,
    app_version,
    ip_address,
    longitude,
    latitude,
    language,
    timezone,
    currency,
    vip_level,
    vip_expire_time,
    is_vip_processed,
    member_points,
    balance,
    credit_score,
    risk_level,
    verify_status,
    level_id,
    level_name,
    level_code,
    level_rank,
    min_points,
    max_points,
    level_icon,
    level_color,
    upgrade_points,
    current_level_points,
    next_level_points,
    progress_percentage,
    privilege_list,
    discount_rate,
    points_rate,
    free_shipping,
    exclusive_products,
    priority_support,
    birthday_bonus,
    monthly_coupon,
    annual_gift,
    vip_service,
    invite_quota,
    max_orders_per_day,
    max_return_days,
    level_benefits,
    upgrade_time,
    downgrade_time,
    maintain_days,
    level_status,
    create_time,
    update_time,
    valid_from,
    valid_to,
    is_active,
    level_tier,
    level_group,
    level_category,
    points_required,
    orders_required,
    amount_required,
    days_required,
    growth_value,
    experience_value,
    contribution_value,
    activity_value,
    loyalty_score,
    engagement_score,
    satisfaction_score,
    retention_score,
    region_id,
    region_code,
    region_name,
    parent_id,
    region_level,
    region_path,
    province_id,
    province_abbr,
    city_id,
    city_abbr,
    district_id,
    district_abbr,
    street_id,
    street_code,
    street_name,
    center_longitude,
    center_latitude,
    area_size,
    population,
    gdp,
    gdp_per_capita,
    climate_type,
    economy_level,
    development_level,
    urban_rate,
    region_type,
    is_coastal,
    is_border,
    is_capital,
    is_special,
    postal_code_prefix,
    phone_area_code,
    car_plate_prefix,
    airport_code,
    railway_station_code,
    port_code,
    weather_station_code,
    customs_code,
    statistical_code,
    iso_code,
    source_code,
    source_category,
    channel_id,
    channel_code,
    channel_name,
    channel_type,
    channel_category,
    campaign_id,
    campaign_code,
    campaign_name,
    campaign_type,
    medium_id,
    medium_code,
    medium_name,
    medium_type,
    term_id,
    term_keyword,
    content_id,
    content_name,
    referral_url,
    landing_page,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    cost_per_acquisition,
    conversion_rate,
    quality_score,
    retention_rate_7d,
    retention_rate_30d,
    lifetime_value,
    first_order_amount,
    first_order_days,
    register_device,
    register_os,
    register_browser,
    register_network,
    register_location,
    attribution_model,
    lookback_days,
    priority,
    is_paid,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slusr.dwb_user_profile_f;

COMMENT ON TABLE slusr.dwb_user_profile_i IS '用户画像宽表（视图）';

COMMENT ON COLUMN slusr.dwb_user_profile_i.user_id IS '用户ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.user_name IS '用户姓名';
COMMENT ON COLUMN slusr.dwb_user_profile_i.user_phone_processed IS '手机号';
COMMENT ON COLUMN slusr.dwb_user_profile_i.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_profile_i.email IS '电子邮箱';
COMMENT ON COLUMN slusr.dwb_user_profile_i.gender_processed IS '性别';
COMMENT ON COLUMN slusr.dwb_user_profile_i.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_profile_i.age_processed IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_profile_i.id_card IS '身份证号';
COMMENT ON COLUMN slusr.dwb_user_profile_i.id_card_masked_processed IS '身份证号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_profile_i.real_name IS '真实姓名';
COMMENT ON COLUMN slusr.dwb_user_profile_i.nick_name IS '昵称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.avatar_url IS '头像URL';
COMMENT ON COLUMN slusr.dwb_user_profile_i.user_status IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_profile_i.user_status_name_processed IS '用户状态名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_date_processed IS '注册日期';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_hour_processed IS '注册小时';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_weekday_processed IS '注册星期';
COMMENT ON COLUMN slusr.dwb_user_profile_i.last_login_time IS '最后登录时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.last_login_date_processed IS '最后登录日期';
COMMENT ON COLUMN slusr.dwb_user_profile_i.login_count IS '登录次数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.province_code IS '省份代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.city_code IS '城市代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.district_code IS '区县代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.district_name IS '区县名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.address IS '详细地址';
COMMENT ON COLUMN slusr.dwb_user_profile_i.zip_code IS '邮政编码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.source_id IS '来源渠道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.source_name IS '来源渠道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.source_type IS '来源类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.device_type IS '设备类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.os_type IS '操作系统';
COMMENT ON COLUMN slusr.dwb_user_profile_i.app_version IS 'APP版本';
COMMENT ON COLUMN slusr.dwb_user_profile_i.ip_address IS 'IP地址';
COMMENT ON COLUMN slusr.dwb_user_profile_i.longitude IS '经度';
COMMENT ON COLUMN slusr.dwb_user_profile_i.latitude IS '纬度';
COMMENT ON COLUMN slusr.dwb_user_profile_i.language IS '语言';
COMMENT ON COLUMN slusr.dwb_user_profile_i.timezone IS '时区';
COMMENT ON COLUMN slusr.dwb_user_profile_i.currency IS '货币';
COMMENT ON COLUMN slusr.dwb_user_profile_i.vip_level IS 'VIP等级';
COMMENT ON COLUMN slusr.dwb_user_profile_i.vip_expire_time IS 'VIP到期时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_vip_processed IS '是否VIP';
COMMENT ON COLUMN slusr.dwb_user_profile_i.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.balance IS '账户余额';
COMMENT ON COLUMN slusr.dwb_user_profile_i.credit_score IS '信用分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.risk_level IS '风险等级';
COMMENT ON COLUMN slusr.dwb_user_profile_i.verify_status IS '认证状态';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_code IS '等级代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_rank IS '等级排序';
COMMENT ON COLUMN slusr.dwb_user_profile_i.min_points IS '最小积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.max_points IS '最大积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_icon IS '等级图标';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_color IS '等级颜色';
COMMENT ON COLUMN slusr.dwb_user_profile_i.upgrade_points IS '升级所需积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.current_level_points IS '当前等级积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.next_level_points IS '下一等级积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.progress_percentage IS '升级进度百分比';
COMMENT ON COLUMN slusr.dwb_user_profile_i.privilege_list IS '权限列表';
COMMENT ON COLUMN slusr.dwb_user_profile_i.discount_rate IS '折扣率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.points_rate IS '积分倍率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.free_shipping IS '免费配送';
COMMENT ON COLUMN slusr.dwb_user_profile_i.exclusive_products IS '专属商品';
COMMENT ON COLUMN slusr.dwb_user_profile_i.priority_support IS '优先客服';
COMMENT ON COLUMN slusr.dwb_user_profile_i.birthday_bonus IS '生日礼金';
COMMENT ON COLUMN slusr.dwb_user_profile_i.monthly_coupon IS '月度优惠券';
COMMENT ON COLUMN slusr.dwb_user_profile_i.annual_gift IS '年度礼品';
COMMENT ON COLUMN slusr.dwb_user_profile_i.vip_service IS 'VIP服务';
COMMENT ON COLUMN slusr.dwb_user_profile_i.invite_quota IS '邀请名额';
COMMENT ON COLUMN slusr.dwb_user_profile_i.max_orders_per_day IS '每日最大订单数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.max_return_days IS '最大退货天数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_benefits IS '等级权益';
COMMENT ON COLUMN slusr.dwb_user_profile_i.upgrade_time IS '升级时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.downgrade_time IS '降级时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.maintain_days IS '维持天数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_status IS '等级状态';
COMMENT ON COLUMN slusr.dwb_user_profile_i.create_time IS '创建时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.update_time IS '更新时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.valid_from IS '生效开始时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.valid_to IS '生效结束时间';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_active IS '是否激活';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_tier IS '等级层级';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_group IS '等级分组';
COMMENT ON COLUMN slusr.dwb_user_profile_i.level_category IS '等级分类';
COMMENT ON COLUMN slusr.dwb_user_profile_i.points_required IS '所需积分';
COMMENT ON COLUMN slusr.dwb_user_profile_i.orders_required IS '所需订单数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.amount_required IS '所需金额';
COMMENT ON COLUMN slusr.dwb_user_profile_i.days_required IS '所需天数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.growth_value IS '成长值';
COMMENT ON COLUMN slusr.dwb_user_profile_i.experience_value IS '经验值';
COMMENT ON COLUMN slusr.dwb_user_profile_i.contribution_value IS '贡献值';
COMMENT ON COLUMN slusr.dwb_user_profile_i.activity_value IS '活跃值';
COMMENT ON COLUMN slusr.dwb_user_profile_i.loyalty_score IS '忠诚度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.engagement_score IS '参与度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.satisfaction_score IS '满意度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.retention_score IS '留存率分数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_id IS '地区ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_code IS '地区代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_name IS '地区名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.parent_id IS '父级ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_level IS '地区层级';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_path IS '地区路径';
COMMENT ON COLUMN slusr.dwb_user_profile_i.province_id IS '省份ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.province_abbr IS '省份简称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.city_id IS '城市ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.city_abbr IS '城市简称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.district_id IS '区县ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.district_abbr IS '区县简称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.street_id IS '街道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.street_code IS '街道代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.street_name IS '街道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.center_longitude IS '中心经度';
COMMENT ON COLUMN slusr.dwb_user_profile_i.center_latitude IS '中心纬度';
COMMENT ON COLUMN slusr.dwb_user_profile_i.area_size IS '区域面积';
COMMENT ON COLUMN slusr.dwb_user_profile_i.population IS '人口数量';
COMMENT ON COLUMN slusr.dwb_user_profile_i.gdp IS 'GDP';
COMMENT ON COLUMN slusr.dwb_user_profile_i.gdp_per_capita IS '人均GDP';
COMMENT ON COLUMN slusr.dwb_user_profile_i.climate_type IS '气候类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.economy_level IS '经济水平';
COMMENT ON COLUMN slusr.dwb_user_profile_i.development_level IS '发展水平';
COMMENT ON COLUMN slusr.dwb_user_profile_i.urban_rate IS '城镇化率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.region_type IS '地区类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_coastal IS '是否沿海';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_border IS '是否边境';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_capital IS '是否省会';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_special IS '是否特区';
COMMENT ON COLUMN slusr.dwb_user_profile_i.postal_code_prefix IS '邮编前缀';
COMMENT ON COLUMN slusr.dwb_user_profile_i.phone_area_code IS '电话区号';
COMMENT ON COLUMN slusr.dwb_user_profile_i.car_plate_prefix IS '车牌前缀';
COMMENT ON COLUMN slusr.dwb_user_profile_i.airport_code IS '机场代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.railway_station_code IS '火车站代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.port_code IS '港口代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.weather_station_code IS '气象站代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.customs_code IS '海关代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.statistical_code IS '统计代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.iso_code IS 'ISO代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.source_code IS '来源代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.source_category IS '来源分类';
COMMENT ON COLUMN slusr.dwb_user_profile_i.channel_id IS '渠道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.channel_code IS '渠道代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.channel_name IS '渠道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.channel_type IS '渠道类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.channel_category IS '渠道分类';
COMMENT ON COLUMN slusr.dwb_user_profile_i.campaign_id IS '活动ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.campaign_code IS '活动代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.campaign_name IS '活动名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.campaign_type IS '活动类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.medium_id IS '媒介ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.medium_code IS '媒介代码';
COMMENT ON COLUMN slusr.dwb_user_profile_i.medium_name IS '媒介名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.medium_type IS '媒介类型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.term_id IS '搜索词ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.term_keyword IS '搜索关键词';
COMMENT ON COLUMN slusr.dwb_user_profile_i.content_id IS '内容ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.content_name IS '内容名称';
COMMENT ON COLUMN slusr.dwb_user_profile_i.referral_url IS '来源URL';
COMMENT ON COLUMN slusr.dwb_user_profile_i.landing_page IS '落地页';
COMMENT ON COLUMN slusr.dwb_user_profile_i.utm_source IS 'UTM来源';
COMMENT ON COLUMN slusr.dwb_user_profile_i.utm_medium IS 'UTM媒介';
COMMENT ON COLUMN slusr.dwb_user_profile_i.utm_campaign IS 'UTM活动';
COMMENT ON COLUMN slusr.dwb_user_profile_i.utm_term IS 'UTM关键词';
COMMENT ON COLUMN slusr.dwb_user_profile_i.utm_content IS 'UTM内容';
COMMENT ON COLUMN slusr.dwb_user_profile_i.cost_per_acquisition IS '获客成本';
COMMENT ON COLUMN slusr.dwb_user_profile_i.conversion_rate IS '转化率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.quality_score IS '质量分数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.retention_rate_7d IS '7日留存率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.retention_rate_30d IS '30日留存率';
COMMENT ON COLUMN slusr.dwb_user_profile_i.lifetime_value IS '生命周期价值';
COMMENT ON COLUMN slusr.dwb_user_profile_i.first_order_amount IS '首单金额';
COMMENT ON COLUMN slusr.dwb_user_profile_i.first_order_days IS '首单天数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_device IS '注册设备';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_os IS '注册系统';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_browser IS '注册浏览器';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_network IS '注册网络';
COMMENT ON COLUMN slusr.dwb_user_profile_i.register_location IS '注册地点';
COMMENT ON COLUMN slusr.dwb_user_profile_i.attribution_model IS '归因模型';
COMMENT ON COLUMN slusr.dwb_user_profile_i.lookback_days IS '回溯天数';
COMMENT ON COLUMN slusr.dwb_user_profile_i.priority IS '优先级';
COMMENT ON COLUMN slusr.dwb_user_profile_i.is_paid IS '是否付费';
COMMENT ON COLUMN slusr.dwb_user_profile_i.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_profile_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_profile_i.dw_last_update_date IS '数仓最后更新时间';
