/* =====================================================
   表名: slusr.dwb_user_profile_f
   规则: R0001 - 用户画像宽表写入
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 以用户基础信息表(oub)为主表（粒度锚点：一个用户），LEFT JOIN 用户等级维度(dul)、地区维度(drd)、用户来源维度(dus)三张维度表补充画像属性，按用户粒度一次性全量写入画像宽表；字段以直取为主，少量字段做脱敏/代码翻译/时间提取加工。单场景、不分段。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_profile_f (
    user_id                    bigint,  /* 用户ID */
    user_name                  varchar(100),  /* 用户姓名 */
    user_phone_processed       varchar(20),  /* 手机号 */
    user_phone_masked          varchar(20),  /* 手机号(脱敏) */
    email                      varchar(100),  /* 电子邮箱 */
    gender_processed           varchar(10),  /* 性别 */
    birthday                   date,  /* 出生日期 */
    age_processed              int,  /* 年龄 */
    id_card                    varchar(20),  /* 身份证号 */
    id_card_masked_processed   varchar(20),  /* 身份证号(脱敏) */
    real_name                  varchar(50),  /* 真实姓名 */
    nick_name                  varchar(50),  /* 昵称 */
    avatar_url                 varchar(500),  /* 头像URL */
    user_status                varchar(20),  /* 用户状态 */
    user_status_name_processed varchar(20),  /* 用户状态名称 */
    register_time              timestamp,  /* 注册时间 */
    register_date_processed    date,  /* 注册日期 */
    register_hour_processed    int,  /* 注册小时 */
    register_weekday_processed int,  /* 注册星期 */
    last_login_time            timestamp,  /* 最后登录时间 */
    last_login_date_processed  date,  /* 最后登录日期 */
    login_count                int,  /* 登录次数 */
    province_code              varchar(20),  /* 省份代码 */
    province_name              varchar(50),  /* 省份名称 */
    city_code                  varchar(20),  /* 城市代码 */
    city_name                  varchar(50),  /* 城市名称 */
    district_code              varchar(20),  /* 区县代码 */
    district_name              varchar(50),  /* 区县名称 */
    address                    varchar(500),  /* 详细地址 */
    zip_code                   varchar(10),  /* 邮政编码 */
    source_id                  int,  /* 来源渠道ID */
    source_name                varchar(50),  /* 来源渠道名称 */
    source_type                varchar(20),  /* 来源类型 */
    device_type                varchar(20),  /* 设备类型 */
    os_type                    varchar(20),  /* 操作系统 */
    app_version                varchar(20),  /* APP版本 */
    ip_address                 varchar(50),  /* IP地址 */
    longitude                  decimal(10,6),  /* 经度 */
    latitude                   decimal(10,6),  /* 纬度 */
    language                   varchar(20),  /* 语言 */
    timezone                   varchar(50),  /* 时区 */
    currency                   varchar(10),  /* 货币 */
    vip_level                  int,  /* VIP等级 */
    vip_expire_time            timestamp,  /* VIP到期时间 */
    is_vip_processed           int,  /* 是否VIP */
    member_points              int,  /* 会员积分 */
    balance                    decimal(18,2),  /* 账户余额 */
    credit_score               int,  /* 信用分 */
    risk_level                 varchar(20),  /* 风险等级 */
    verify_status              varchar(20),  /* 认证状态 */
    level_id                   int,  /* 等级ID */
    level_name                 varchar(50),  /* 等级名称 */
    level_code                 varchar(20),  /* 等级代码 */
    level_rank                 int,  /* 等级排序 */
    min_points                 int,  /* 最小积分 */
    max_points                 int,  /* 最大积分 */
    level_icon                 varchar(500),  /* 等级图标 */
    level_color                varchar(20),  /* 等级颜色 */
    upgrade_points             int,  /* 升级所需积分 */
    current_level_points       int,  /* 当前等级积分 */
    next_level_points          int,  /* 下一等级积分 */
    progress_percentage        decimal(5,2),  /* 升级进度百分比 */
    privilege_list             varchar(1000),  /* 权限列表 */
    discount_rate              decimal(5,2),  /* 折扣率 */
    points_rate                decimal(5,2),  /* 积分倍率 */
    free_shipping              int,  /* 免费配送 */
    exclusive_products         int,  /* 专属商品 */
    priority_support           int,  /* 优先客服 */
    birthday_bonus             int,  /* 生日礼金 */
    monthly_coupon             int,  /* 月度优惠券 */
    annual_gift                int,  /* 年度礼品 */
    vip_service                int,  /* VIP服务 */
    invite_quota               int,  /* 邀请名额 */
    max_orders_per_day         int,  /* 每日最大订单数 */
    max_return_days            int,  /* 最大退货天数 */
    level_benefits             varchar(1000),  /* 等级权益 */
    upgrade_time               timestamp,  /* 升级时间 */
    downgrade_time             timestamp,  /* 降级时间 */
    maintain_days              int,  /* 维持天数 */
    level_status               varchar(20),  /* 等级状态 */
    create_time                timestamp,  /* 创建时间 */
    update_time                timestamp,  /* 更新时间 */
    valid_from                 timestamp,  /* 生效开始时间 */
    valid_to                   timestamp,  /* 生效结束时间 */
    is_active                  int,  /* 是否激活 */
    level_tier                 int,  /* 等级层级 */
    level_group                varchar(50),  /* 等级分组 */
    level_category             varchar(50),  /* 等级分类 */
    points_required            int,  /* 所需积分 */
    orders_required            int,  /* 所需订单数 */
    amount_required            decimal(18,2),  /* 所需金额 */
    days_required              int,  /* 所需天数 */
    growth_value               int,  /* 成长值 */
    experience_value           int,  /* 经验值 */
    contribution_value         int,  /* 贡献值 */
    activity_value             int,  /* 活跃值 */
    loyalty_score              decimal(5,2),  /* 忠诚度分数 */
    engagement_score           decimal(5,2),  /* 参与度分数 */
    satisfaction_score         decimal(5,2),  /* 满意度分数 */
    retention_score            decimal(5,2),  /* 留存率分数 */
    region_id                  int,  /* 地区ID */
    region_code                varchar(20),  /* 地区代码 */
    region_name                varchar(100),  /* 地区名称 */
    parent_id                  int,  /* 父级ID */
    region_level               int,  /* 地区层级 */
    region_path                varchar(500),  /* 地区路径 */
    province_id                int,  /* 省份ID */
    province_abbr              varchar(20),  /* 省份简称 */
    city_id                    int,  /* 城市ID */
    city_abbr                  varchar(20),  /* 城市简称 */
    district_id                int,  /* 区县ID */
    district_abbr              varchar(20),  /* 区县简称 */
    street_id                  int,  /* 街道ID */
    street_code                varchar(20),  /* 街道代码 */
    street_name                varchar(50),  /* 街道名称 */
    center_longitude           decimal(10,6),  /* 中心经度 */
    center_latitude            decimal(10,6),  /* 中心纬度 */
    area_size                  decimal(18,2),  /* 区域面积 */
    population                 int,  /* 人口数量 */
    gdp                        decimal(18,2),  /* GDP */
    gdp_per_capita             decimal(18,2),  /* 人均GDP */
    climate_type               varchar(50),  /* 气候类型 */
    economy_level              varchar(50),  /* 经济水平 */
    development_level          varchar(50),  /* 发展水平 */
    urban_rate                 decimal(5,2),  /* 城镇化率 */
    region_type                varchar(50),  /* 地区类型 */
    is_coastal                 int,  /* 是否沿海 */
    is_border                  int,  /* 是否边境 */
    is_capital                 int,  /* 是否省会 */
    is_special                 int,  /* 是否特区 */
    postal_code_prefix         varchar(10),  /* 邮编前缀 */
    phone_area_code            varchar(20),  /* 电话区号 */
    car_plate_prefix           varchar(10),  /* 车牌前缀 */
    airport_code               varchar(10),  /* 机场代码 */
    railway_station_code       varchar(20),  /* 火车站代码 */
    port_code                  varchar(20),  /* 港口代码 */
    weather_station_code       varchar(20),  /* 气象站代码 */
    customs_code               varchar(20),  /* 海关代码 */
    statistical_code           varchar(20),  /* 统计代码 */
    iso_code                   varchar(20),  /* ISO代码 */
    source_code                varchar(50),  /* 来源代码 */
    source_category            varchar(50),  /* 来源分类 */
    channel_id                 int,  /* 渠道ID */
    channel_code               varchar(50),  /* 渠道代码 */
    channel_name               varchar(100),  /* 渠道名称 */
    channel_type               varchar(50),  /* 渠道类型 */
    channel_category           varchar(50),  /* 渠道分类 */
    campaign_id                int,  /* 活动ID */
    campaign_code              varchar(50),  /* 活动代码 */
    campaign_name              varchar(100),  /* 活动名称 */
    campaign_type              varchar(50),  /* 活动类型 */
    medium_id                  int,  /* 媒介ID */
    medium_code                varchar(50),  /* 媒介代码 */
    medium_name                varchar(100),  /* 媒介名称 */
    medium_type                varchar(50),  /* 媒介类型 */
    term_id                    int,  /* 搜索词ID */
    term_keyword               varchar(200),  /* 搜索关键词 */
    content_id                 int,  /* 内容ID */
    content_name               varchar(200),  /* 内容名称 */
    referral_url               varchar(500),  /* 来源URL */
    landing_page               varchar(500),  /* 落地页 */
    utm_source                 varchar(100),  /* UTM来源 */
    utm_medium                 varchar(100),  /* UTM媒介 */
    utm_campaign               varchar(100),  /* UTM活动 */
    utm_term                   varchar(100),  /* UTM关键词 */
    utm_content                varchar(100),  /* UTM内容 */
    cost_per_acquisition       decimal(18,2),  /* 获客成本 */
    conversion_rate            decimal(5,2),  /* 转化率 */
    quality_score              decimal(5,2),  /* 质量分数 */
    retention_rate_7d          decimal(5,2),  /* 7日留存率 */
    retention_rate_30d         decimal(5,2),  /* 30日留存率 */
    lifetime_value             decimal(18,2),  /* 生命周期价值 */
    first_order_amount         decimal(18,2),  /* 首单金额 */
    first_order_days           int,  /* 首单天数 */
    register_device            varchar(50),  /* 注册设备 */
    register_os                varchar(50),  /* 注册系统 */
    register_browser           varchar(50),  /* 注册浏览器 */
    register_network           varchar(50),  /* 注册网络 */
    register_location          varchar(200),  /* 注册地点 */
    attribution_model          varchar(50),  /* 归因模型 */
    lookback_days              int,  /* 回溯天数 */
    priority                   int,  /* 优先级 */
    is_paid                    int,  /* 是否付费 */
    del_flag                   NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id               BIGINT,  /* 创建批次ID */
    last_upd_cycle_id          BIGINT,  /* 最后更新批次ID */
    dw_last_update_date        TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
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
