/* =====================================================
   表名: slusr.dwb_user_profile_f
   规则: R0001 - 用户画像宽表全量加工
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 用户画像宽表全量重写：以 oub 用户基础表为主表，LEFT JOIN 等级/地区/来源三张维表补齐画像属性，并对敏感字段脱敏、枚举字段转中文、派生时间维度字段。无粒度变化、无聚合，单条 INSERT 即可完成。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_profile_f (
    user_id                    bigint,
    user_name                  varchar(100),
    user_phone_processed       varchar(20),
    user_phone_masked          varchar(20),
    email                      varchar(100),
    gender_processed           varchar(10),
    birthday                   date,
    age_processed              int,
    id_card                    varchar(20),
    id_card_masked_processed   varchar(20),
    real_name                  varchar(50),
    nick_name                  varchar(50),
    avatar_url                 varchar(500),
    user_status                varchar(20),
    user_status_name_processed varchar(20),
    register_time              timestamp,
    register_date_processed    date,
    register_hour_processed    int,
    register_weekday_processed int,
    last_login_time            timestamp,
    last_login_date_processed  date,
    login_count                int,
    province_code              varchar(20),
    province_name              varchar(50),
    city_code                  varchar(20),
    city_name                  varchar(50),
    district_code              varchar(20),
    district_name              varchar(50),
    address                    varchar(500),
    zip_code                   varchar(10),
    source_id                  int,
    source_name                varchar(50),
    source_type                varchar(20),
    device_type                varchar(20),
    os_type                    varchar(20),
    app_version                varchar(20),
    ip_address                 varchar(50),
    longitude                  decimal(10,6),
    latitude                   decimal(10,6),
    language                   varchar(20),
    timezone                   varchar(50),
    currency                   varchar(10),
    vip_level                  int,
    vip_expire_time            timestamp,
    is_vip_processed           int,
    member_points              int,
    balance                    decimal(18,2),
    credit_score               int,
    risk_level                 varchar(20),
    verify_status              varchar(20),
    level_id                   int,
    level_name                 varchar(50),
    level_code                 varchar(20),
    level_rank                 int,
    min_points                 int,
    max_points                 int,
    level_icon                 varchar(500),
    level_color                varchar(20),
    upgrade_points             int,
    current_level_points       int,
    next_level_points          int,
    progress_percentage        decimal(5,2),
    privilege_list             varchar(1000),
    discount_rate              decimal(5,2),
    points_rate                decimal(5,2),
    free_shipping              int,
    exclusive_products         int,
    priority_support           int,
    birthday_bonus             int,
    monthly_coupon             int,
    annual_gift                int,
    vip_service                int,
    invite_quota               int,
    max_orders_per_day         int,
    max_return_days            int,
    level_benefits             varchar(1000),
    upgrade_time               timestamp,
    downgrade_time             timestamp,
    maintain_days              int,
    level_status               varchar(20),
    create_time                timestamp,
    update_time                timestamp,
    valid_from                 timestamp,
    valid_to                   timestamp,
    is_active                  int,
    level_tier                 int,
    level_group                varchar(50),
    level_category             varchar(50),
    points_required            int,
    orders_required            int,
    amount_required            decimal(18,2),
    days_required              int,
    growth_value               int,
    experience_value           int,
    contribution_value         int,
    activity_value             int,
    loyalty_score              decimal(5,2),
    engagement_score           decimal(5,2),
    satisfaction_score         decimal(5,2),
    retention_score            decimal(5,2),
    region_id                  int,
    region_code                varchar(20),
    region_name                varchar(100),
    parent_id                  int,
    region_level               int,
    region_path                varchar(500),
    province_id                int,
    province_abbr              varchar(20),
    city_id                    int,
    city_abbr                  varchar(20),
    district_id                int,
    district_abbr              varchar(20),
    street_id                  int,
    street_code                varchar(20),
    street_name                varchar(50),
    center_longitude           decimal(10,6),
    center_latitude            decimal(10,6),
    area_size                  decimal(18,2),
    population                 int,
    gdp                        decimal(18,2),
    gdp_per_capita             decimal(18,2),
    climate_type               varchar(50),
    economy_level              varchar(50),
    development_level          varchar(50),
    urban_rate                 decimal(5,2),
    region_type                varchar(50),
    is_coastal                 int,
    is_border                  int,
    is_capital                 int,
    is_special                 int,
    postal_code_prefix         varchar(10),
    phone_area_code            varchar(20),
    car_plate_prefix           varchar(10),
    airport_code               varchar(10),
    railway_station_code       varchar(20),
    port_code                  varchar(20),
    weather_station_code       varchar(20),
    customs_code               varchar(20),
    statistical_code           varchar(20),
    iso_code                   varchar(20),
    source_code                varchar(50),
    source_category            varchar(50),
    channel_id                 int,
    channel_code               varchar(50),
    channel_name               varchar(100),
    channel_type               varchar(50),
    channel_category           varchar(50),
    campaign_id                int,
    campaign_code              varchar(50),
    campaign_name              varchar(100),
    campaign_type              varchar(50),
    medium_id                  int,
    medium_code                varchar(50),
    medium_name                varchar(100),
    medium_type                varchar(50),
    term_id                    int,
    term_keyword               varchar(200),
    content_id                 int,
    content_name               varchar(200),
    referral_url               varchar(500),
    landing_page               varchar(500),
    utm_source                 varchar(100),
    utm_medium                 varchar(100),
    utm_campaign               varchar(100),
    utm_term                   varchar(100),
    utm_content                varchar(100),
    cost_per_acquisition       decimal(18,2),
    conversion_rate            decimal(5,2),
    quality_score              decimal(5,2),
    retention_rate_7d          decimal(5,2),
    retention_rate_30d         decimal(5,2),
    lifetime_value             decimal(18,2),
    first_order_amount         decimal(18,2),
    first_order_days           int,
    register_device            varchar(50),
    register_os                varchar(50),
    register_browser           varchar(50),
    register_network           varchar(50),
    register_location          varchar(200),
    attribution_model          varchar(50),
    lookback_days              int,
    priority                   int,
    is_paid                    int,
    del_flag                   NVARCHAR(1),
    crt_cycle_id               BIGINT,
    last_upd_cycle_id          BIGINT,
    dw_last_update_date        TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_profile_f IS '用户画像宽表';

COMMENT ON COLUMN slusr.dwb_user_profile_f.user_id IS '用户ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.user_name IS '用户姓名';
COMMENT ON COLUMN slusr.dwb_user_profile_f.user_phone_processed IS '手机号';
COMMENT ON COLUMN slusr.dwb_user_profile_f.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_profile_f.email IS '电子邮箱';
COMMENT ON COLUMN slusr.dwb_user_profile_f.gender_processed IS '性别';
COMMENT ON COLUMN slusr.dwb_user_profile_f.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_profile_f.age_processed IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_profile_f.id_card IS '身份证号';
COMMENT ON COLUMN slusr.dwb_user_profile_f.id_card_masked_processed IS '身份证号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_profile_f.real_name IS '真实姓名';
COMMENT ON COLUMN slusr.dwb_user_profile_f.nick_name IS '昵称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.avatar_url IS '头像URL';
COMMENT ON COLUMN slusr.dwb_user_profile_f.user_status IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_profile_f.user_status_name_processed IS '用户状态名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_date_processed IS '注册日期';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_hour_processed IS '注册小时';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_weekday_processed IS '注册星期';
COMMENT ON COLUMN slusr.dwb_user_profile_f.last_login_time IS '最后登录时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.last_login_date_processed IS '最后登录日期';
COMMENT ON COLUMN slusr.dwb_user_profile_f.login_count IS '登录次数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.province_code IS '省份代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.city_code IS '城市代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.district_code IS '区县代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.district_name IS '区县名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.address IS '详细地址';
COMMENT ON COLUMN slusr.dwb_user_profile_f.zip_code IS '邮政编码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.source_id IS '来源渠道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.source_name IS '来源渠道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.source_type IS '来源类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.device_type IS '设备类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.os_type IS '操作系统';
COMMENT ON COLUMN slusr.dwb_user_profile_f.app_version IS 'APP版本';
COMMENT ON COLUMN slusr.dwb_user_profile_f.ip_address IS 'IP地址';
COMMENT ON COLUMN slusr.dwb_user_profile_f.longitude IS '经度';
COMMENT ON COLUMN slusr.dwb_user_profile_f.latitude IS '纬度';
COMMENT ON COLUMN slusr.dwb_user_profile_f.language IS '语言';
COMMENT ON COLUMN slusr.dwb_user_profile_f.timezone IS '时区';
COMMENT ON COLUMN slusr.dwb_user_profile_f.currency IS '货币';
COMMENT ON COLUMN slusr.dwb_user_profile_f.vip_level IS 'VIP等级';
COMMENT ON COLUMN slusr.dwb_user_profile_f.vip_expire_time IS 'VIP到期时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_vip_processed IS '是否VIP';
COMMENT ON COLUMN slusr.dwb_user_profile_f.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.balance IS '账户余额';
COMMENT ON COLUMN slusr.dwb_user_profile_f.credit_score IS '信用分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.risk_level IS '风险等级';
COMMENT ON COLUMN slusr.dwb_user_profile_f.verify_status IS '认证状态';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_code IS '等级代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_rank IS '等级排序';
COMMENT ON COLUMN slusr.dwb_user_profile_f.min_points IS '最小积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.max_points IS '最大积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_icon IS '等级图标';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_color IS '等级颜色';
COMMENT ON COLUMN slusr.dwb_user_profile_f.upgrade_points IS '升级所需积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.current_level_points IS '当前等级积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.next_level_points IS '下一等级积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.progress_percentage IS '升级进度百分比';
COMMENT ON COLUMN slusr.dwb_user_profile_f.privilege_list IS '权限列表';
COMMENT ON COLUMN slusr.dwb_user_profile_f.discount_rate IS '折扣率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.points_rate IS '积分倍率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.free_shipping IS '免费配送';
COMMENT ON COLUMN slusr.dwb_user_profile_f.exclusive_products IS '专属商品';
COMMENT ON COLUMN slusr.dwb_user_profile_f.priority_support IS '优先客服';
COMMENT ON COLUMN slusr.dwb_user_profile_f.birthday_bonus IS '生日礼金';
COMMENT ON COLUMN slusr.dwb_user_profile_f.monthly_coupon IS '月度优惠券';
COMMENT ON COLUMN slusr.dwb_user_profile_f.annual_gift IS '年度礼品';
COMMENT ON COLUMN slusr.dwb_user_profile_f.vip_service IS 'VIP服务';
COMMENT ON COLUMN slusr.dwb_user_profile_f.invite_quota IS '邀请名额';
COMMENT ON COLUMN slusr.dwb_user_profile_f.max_orders_per_day IS '每日最大订单数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.max_return_days IS '最大退货天数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_benefits IS '等级权益';
COMMENT ON COLUMN slusr.dwb_user_profile_f.upgrade_time IS '升级时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.downgrade_time IS '降级时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.maintain_days IS '维持天数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_status IS '等级状态';
COMMENT ON COLUMN slusr.dwb_user_profile_f.create_time IS '创建时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.update_time IS '更新时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.valid_from IS '生效开始时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.valid_to IS '生效结束时间';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_active IS '是否激活';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_tier IS '等级层级';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_group IS '等级分组';
COMMENT ON COLUMN slusr.dwb_user_profile_f.level_category IS '等级分类';
COMMENT ON COLUMN slusr.dwb_user_profile_f.points_required IS '所需积分';
COMMENT ON COLUMN slusr.dwb_user_profile_f.orders_required IS '所需订单数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.amount_required IS '所需金额';
COMMENT ON COLUMN slusr.dwb_user_profile_f.days_required IS '所需天数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.growth_value IS '成长值';
COMMENT ON COLUMN slusr.dwb_user_profile_f.experience_value IS '经验值';
COMMENT ON COLUMN slusr.dwb_user_profile_f.contribution_value IS '贡献值';
COMMENT ON COLUMN slusr.dwb_user_profile_f.activity_value IS '活跃值';
COMMENT ON COLUMN slusr.dwb_user_profile_f.loyalty_score IS '忠诚度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.engagement_score IS '参与度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.satisfaction_score IS '满意度分数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.retention_score IS '留存率分数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_id IS '地区ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_code IS '地区代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_name IS '地区名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.parent_id IS '父级ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_level IS '地区层级';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_path IS '地区路径';
COMMENT ON COLUMN slusr.dwb_user_profile_f.province_id IS '省份ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.province_abbr IS '省份简称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.city_id IS '城市ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.city_abbr IS '城市简称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.district_id IS '区县ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.district_abbr IS '区县简称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.street_id IS '街道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.street_code IS '街道代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.street_name IS '街道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.center_longitude IS '中心经度';
COMMENT ON COLUMN slusr.dwb_user_profile_f.center_latitude IS '中心纬度';
COMMENT ON COLUMN slusr.dwb_user_profile_f.area_size IS '区域面积';
COMMENT ON COLUMN slusr.dwb_user_profile_f.population IS '人口数量';
COMMENT ON COLUMN slusr.dwb_user_profile_f.gdp IS 'GDP';
COMMENT ON COLUMN slusr.dwb_user_profile_f.gdp_per_capita IS '人均GDP';
COMMENT ON COLUMN slusr.dwb_user_profile_f.climate_type IS '气候类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.economy_level IS '经济水平';
COMMENT ON COLUMN slusr.dwb_user_profile_f.development_level IS '发展水平';
COMMENT ON COLUMN slusr.dwb_user_profile_f.urban_rate IS '城镇化率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.region_type IS '地区类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_coastal IS '是否沿海';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_border IS '是否边境';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_capital IS '是否省会';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_special IS '是否特区';
COMMENT ON COLUMN slusr.dwb_user_profile_f.postal_code_prefix IS '邮编前缀';
COMMENT ON COLUMN slusr.dwb_user_profile_f.phone_area_code IS '电话区号';
COMMENT ON COLUMN slusr.dwb_user_profile_f.car_plate_prefix IS '车牌前缀';
COMMENT ON COLUMN slusr.dwb_user_profile_f.airport_code IS '机场代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.railway_station_code IS '火车站代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.port_code IS '港口代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.weather_station_code IS '气象站代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.customs_code IS '海关代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.statistical_code IS '统计代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.iso_code IS 'ISO代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.source_code IS '来源代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.source_category IS '来源分类';
COMMENT ON COLUMN slusr.dwb_user_profile_f.channel_id IS '渠道ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.channel_code IS '渠道代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.channel_name IS '渠道名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.channel_type IS '渠道类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.channel_category IS '渠道分类';
COMMENT ON COLUMN slusr.dwb_user_profile_f.campaign_id IS '活动ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.campaign_code IS '活动代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.campaign_name IS '活动名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.campaign_type IS '活动类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.medium_id IS '媒介ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.medium_code IS '媒介代码';
COMMENT ON COLUMN slusr.dwb_user_profile_f.medium_name IS '媒介名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.medium_type IS '媒介类型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.term_id IS '搜索词ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.term_keyword IS '搜索关键词';
COMMENT ON COLUMN slusr.dwb_user_profile_f.content_id IS '内容ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.content_name IS '内容名称';
COMMENT ON COLUMN slusr.dwb_user_profile_f.referral_url IS '来源URL';
COMMENT ON COLUMN slusr.dwb_user_profile_f.landing_page IS '落地页';
COMMENT ON COLUMN slusr.dwb_user_profile_f.utm_source IS 'UTM来源';
COMMENT ON COLUMN slusr.dwb_user_profile_f.utm_medium IS 'UTM媒介';
COMMENT ON COLUMN slusr.dwb_user_profile_f.utm_campaign IS 'UTM活动';
COMMENT ON COLUMN slusr.dwb_user_profile_f.utm_term IS 'UTM关键词';
COMMENT ON COLUMN slusr.dwb_user_profile_f.utm_content IS 'UTM内容';
COMMENT ON COLUMN slusr.dwb_user_profile_f.cost_per_acquisition IS '获客成本';
COMMENT ON COLUMN slusr.dwb_user_profile_f.conversion_rate IS '转化率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.quality_score IS '质量分数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.retention_rate_7d IS '7日留存率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.retention_rate_30d IS '30日留存率';
COMMENT ON COLUMN slusr.dwb_user_profile_f.lifetime_value IS '生命周期价值';
COMMENT ON COLUMN slusr.dwb_user_profile_f.first_order_amount IS '首单金额';
COMMENT ON COLUMN slusr.dwb_user_profile_f.first_order_days IS '首单天数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_device IS '注册设备';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_os IS '注册系统';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_browser IS '注册浏览器';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_network IS '注册网络';
COMMENT ON COLUMN slusr.dwb_user_profile_f.register_location IS '注册地点';
COMMENT ON COLUMN slusr.dwb_user_profile_f.attribution_model IS '归因模型';
COMMENT ON COLUMN slusr.dwb_user_profile_f.lookback_days IS '回溯天数';
COMMENT ON COLUMN slusr.dwb_user_profile_f.priority IS '优先级';
COMMENT ON COLUMN slusr.dwb_user_profile_f.is_paid IS '是否付费';
COMMENT ON COLUMN slusr.dwb_user_profile_f.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_profile_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_profile_f.dw_last_update_date IS '数仓最后更新时间';
