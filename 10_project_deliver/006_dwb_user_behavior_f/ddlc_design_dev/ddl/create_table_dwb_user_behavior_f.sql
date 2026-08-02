/* =====================================================
   表名: slord.dwb_user_behavior_f
   规则: R0001 - 用户行为宽表三场景 UNION ALL 加工
   分布键: behavior_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 将三类互斥的用户行为事件流（电商交易、内容互动、社交关系）按统一的 用户+行为+领域扩展 字段模型 UNION ALL 合并到一张行为宽表。 因 user_* 与通用行为字段在三场景物理上同属每一行，无法分配到多条场景规则， 故用单条 INSERT 承载全部 184 个目标字段，三场景作为并联 JOIN 子图 在同一规则的 SQL 内并行产出，最终 UNION ALL。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_user_behavior_f (
    user_user_id                   bigint,  /* 用户ID */
    user_user_name                 varchar(100),  /* 用户姓名 */
    user_user_phone                varchar(20),  /* 手机号 */
    user_gender                    varchar(10),  /* 性别 */
    user_age                       int,  /* 年龄 */
    user_birthday                  date,  /* 出生日期 */
    user_province_name             varchar(50),  /* 省份 */
    user_city_name                 varchar(50),  /* 城市 */
    user_user_level                int,  /* 用户等级 */
    user_user_level_name           varchar(50),  /* 用户等级名称 */
    user_vip_status                int,  /* VIP状态 */
    user_register_time             timestamp,  /* 注册时间 */
    user_register_date             date,  /* 注册日期 */
    user_user_status               varchar(20),  /* 用户状态 */
    user_user_status_name          varchar(50),  /* 用户状态名称 */
    user_source_channel            varchar(50),  /* 来源渠道 */
    user_source_type               varchar(50),  /* 来源类型 */
    user_first_active_time         timestamp,  /* 首次活跃时间 */
    user_last_active_time          timestamp,  /* 最后活跃时间 */
    user_active_days               int,  /* 活跃天数 */
    user_total_score               int,  /* 总积分 */
    user_credit_score              int,  /* 信用分 */
    user_risk_level                varchar(20),  /* 风险等级 */
    user_device_type               varchar(50),  /* 设备类型 */
    user_os_type                   varchar(50),  /* 操作系统 */
    user_app_version               varchar(20),  /* APP版本 */
    user_ip_address                varchar(50),  /* IP地址 */
    user_network_type              varchar(20),  /* 网络类型 */
    user_is_real_name              int,  /* 是否实名 */
    user_verify_status             varchar(20),  /* 认证状态 */
    behavior_id                    bigint,  /* 行为ID */
    behavior_time                  timestamp,  /* 行为时间 */
    behavior_date                  date,  /* 行为日期 */
    behavior_hour                  int,  /* 行为小时 */
    behavior_weekday               int,  /* 行为星期 */
    behavior_month                 int,  /* 行为月份 */
    behavior_quarter               int,  /* 行为季度 */
    behavior_year                  int,  /* 行为年份 */
    is_weekend                     int,  /* 是否周末 */
    time_period                    varchar(20),  /* 时间段 */
    order_order_id                 bigint,  /* 订单ID */
    order_order_no                 varchar(50),  /* 订单编号 */
    order_order_status             varchar(20),  /* 订单状态 */
    order_order_status_name        varchar(50),  /* 订单状态名称 */
    order_order_amount             decimal(18,2),  /* 订单金额 */
    order_discount_amount          decimal(18,2),  /* 优惠金额 */
    order_actual_amount            decimal(18,2),  /* 实付金额 */
    order_payment_method           varchar(50),  /* 支付方式 */
    order_payment_time             timestamp,  /* 支付时间 */
    order_shipping_fee             decimal(18,2),  /* 运费 */
    order_product_count            int,  /* 商品数量 */
    order_sku_count                int,  /* SKU数量 */
    order_is_first_order           int,  /* 是否首单 */
    order_coupon_id                int,  /* 优惠券ID */
    order_coupon_name              varchar(100),  /* 优惠券名称 */
    order_points_used              int,  /* 使用积分 */
    order_points_earned            int,  /* 获得积分 */
    order_complete_time            timestamp,  /* 完成时间 */
    order_cancel_time              timestamp,  /* 取消时间 */
    order_cancel_reason            varchar(200),  /* 取消原因 */
    order_merchant_id              int,  /* 商家ID */
    order_merchant_name            varchar(200),  /* 商家名称 */
    order_delivery_type            varchar(50),  /* 配送方式 */
    order_delivery_time            timestamp,  /* 配送时间 */
    order_receive_time             timestamp,  /* 收货时间 */
    order_receive_status           varchar(20),  /* 收货状态 */
    order_order_source             varchar(50),  /* 订单来源 */
    order_remark                   varchar(500),  /* 订单备注 */
    order_invoice_type             varchar(20),  /* 发票类型 */
    order_invoice_title            varchar(200),  /* 发票抬头 */
    prod_product_id                bigint,  /* 商品ID */
    prod_product_name              varchar(200),  /* 商品名称 */
    prod_product_code              varchar(50),  /* 商品编码 */
    prod_sku_id                    bigint,  /* SKU_ID */
    prod_sku_name                  varchar(200),  /* SKU名称 */
    prod_brand_id                  int,  /* 品牌ID */
    prod_brand_name                varchar(100),  /* 品牌名称 */
    prod_category_id               int,  /* 类目ID */
    prod_category_name             varchar(100),  /* 类目名称 */
    prod_category_level1           varchar(100),  /* 一级类目 */
    prod_category_level2           varchar(100),  /* 二级类目 */
    prod_category_level3           varchar(100),  /* 三级类目 */
    prod_price                     decimal(18,2),  /* 商品价格 */
    prod_cost_price                decimal(18,2),  /* 成本价 */
    prod_profit_rate               decimal(5,2),  /* 利润率 */
    prod_stock_status              varchar(20),  /* 库存状态 */
    prod_sale_status               varchar(20),  /* 销售状态 */
    prod_product_type              varchar(50),  /* 商品类型 */
    prod_is_virtual                int,  /* 是否虚拟商品 */
    prod_supplier_id               int,  /* 供应商ID */
    content_interaction_id         bigint,  /* 互动ID */
    content_content_id             bigint,  /* 内容ID */
    content_interaction_type       varchar(50),  /* 互动类型 */
    content_interaction_type_name  varchar(50),  /* 互动类型名称 */
    content_duration_seconds       int,  /* 浏览时长(秒) */
    content_duration_minutes       decimal(5,2),  /* 浏览时长(分) */
    content_comment_content        varchar(1000),  /* 评论内容 */
    content_comment_word_count     int,  /* 评论字数 */
    content_share_platform         varchar(50),  /* 分享平台 */
    content_share_count            int,  /* 分享次数 */
    content_like_count             int,  /* 点赞数 */
    content_comment_count          int,  /* 评论数 */
    content_collect_count          int,  /* 收藏数 */
    content_forward_count          int,  /* 转发数 */
    content_is_original            int,  /* 是否原创 */
    content_source_type            varchar(50),  /* 来源类型 */
    content_browse_depth           int,  /* 浏览深度 */
    content_scroll_percentage      decimal(5,2),  /* 滚动百分比 */
    content_click_count            int,  /* 点击次数 */
    content_stay_time              int,  /* 停留时长 */
    content_bounce_flag            int,  /* 是否跳出 */
    content_exit_page              varchar(200),  /* 退出页面 */
    content_session_id             varchar(100),  /* 会话ID */
    content_page_view_count        int,  /* 页面浏览数 */
    content_unique_visitor         int,  /* 独立访客标识 */
    content_referer_url            varchar(500),  /* 来源URL */
    content_utm_source             varchar(100),  /* UTM来源 */
    content_utm_medium             varchar(100),  /* UTM媒介 */
    content_utm_campaign           varchar(100),  /* UTM活动 */
    content_interaction_device     varchar(50),  /* 互动设备 */
    content_content_title          varchar(200),  /* 内容标题 */
    content_content_type           varchar(50),  /* 内容类型 */
    content_content_category       varchar(50),  /* 内容分类 */
    content_author_id              bigint,  /* 作者ID */
    content_author_name            varchar(100),  /* 作者名称 */
    content_publish_time           timestamp,  /* 发布时间 */
    content_publish_date           date,  /* 发布日期 */
    content_content_length         int,  /* 内容长度 */
    content_word_count             int,  /* 字数 */
    content_read_count             int,  /* 阅读数 */
    content_content_like_count     int,  /* 内容点赞数 */
    content_content_comment_count  int,  /* 内容评论数 */
    content_content_share_count    int,  /* 内容分享数 */
    content_content_collect_count  int,  /* 内容收藏数 */
    content_topic_id               int,  /* 话题ID */
    content_topic_name             varchar(100),  /* 话题名称 */
    content_is_hot                 int,  /* 是否热门 */
    content_is_recommend           int,  /* 是否推荐 */
    content_content_status         varchar(20),  /* 内容状态 */
    content_content_score          decimal(5,2),  /* 内容评分 */
    social_relation_id             bigint,  /* 关系ID */
    social_target_user_id          bigint,  /* 目标用户ID */
    social_relation_type           varchar(50),  /* 关系类型 */
    social_relation_type_name      varchar(50),  /* 关系类型名称 */
    social_is_mutual               int,  /* 是否互相关注 */
    social_interaction_count       int,  /* 互动次数 */
    social_last_interaction_time   timestamp,  /* 最后互动时间 */
    social_relation_status         varchar(20),  /* 关系状态 */
    social_source                  varchar(50),  /* 来源 */
    social_group_id                int,  /* 分组ID */
    social_group_name              varchar(100),  /* 分组名称 */
    social_remark                  varchar(100),  /* 备注名 */
    social_intimacy_level          int,  /* 亲密度等级 */
    social_chat_count              int,  /* 聊天次数 */
    social_call_count              int,  /* 通话次数 */
    social_video_call_count        int,  /* 视频通话次数 */
    social_gift_count              int,  /* 礼物次数 */
    social_follow_days             int,  /* 关注天数 */
    social_interaction_frequency   decimal(5,2),  /* 互动频率 */
    social_common_friends          int,  /* 共同好友数 */
    social_common_groups           int,  /* 共同群组数 */
    social_social_distance         int,  /* 社交距离 */
    social_relationship_strength   decimal(5,2),  /* 关系强度 */
    social_trust_level             int,  /* 信任等级 */
    social_contact_importance      decimal(5,2),  /* 联系人重要性 */
    profile_avatar_url             varchar(500),  /* 头像URL */
    profile_profession             varchar(50),  /* 职业 */
    profile_education              varchar(50),  /* 学历 */
    profile_interests              varchar(500),  /* 兴趣标签 */
    profile_active_level           varchar(20),  /* 活跃等级 */
    profile_influence_score        decimal(5,2),  /* 影响力分数 */
    profile_social_value           decimal(18,2),  /* 社交价值 */
    profile_user_tags              varchar(500),  /* 用户标签 */
    profile_fans_count             int,  /* 粉丝数 */
    profile_follow_count           int,  /* 关注数 */
    profile_friend_count           int,  /* 好友数 */
    profile_social_activity_score  decimal(5,2),  /* 社交活跃度 */
    profile_content_creation_score decimal(5,2),  /* 内容创作力 */
    profile_engagement_score       decimal(5,2),  /* 参与度分数 */
    profile_social_influence_rank  int,  /* 社交影响力排名 */
    del_flag                       NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id                   BIGINT,  /* 创建批次ID */
    last_upd_cycle_id              BIGINT,  /* 最后更新批次ID */
    dw_last_update_date            TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(behavior_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_user_behavior_f IS '用户行为宽表';

COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_id IS '用户ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_name IS '用户姓名';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_phone IS '手机号';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_gender IS '性别';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_age IS '年龄';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_birthday IS '出生日期';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_province_name IS '省份';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_city_name IS '城市';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_level IS '用户等级';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_level_name IS '用户等级名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_vip_status IS 'VIP状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_register_time IS '注册时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_register_date IS '注册日期';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_status IS '用户状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_user_status_name IS '用户状态名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_source_channel IS '来源渠道';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_source_type IS '来源类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_first_active_time IS '首次活跃时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_last_active_time IS '最后活跃时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_active_days IS '活跃天数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_total_score IS '总积分';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_credit_score IS '信用分';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_risk_level IS '风险等级';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_device_type IS '设备类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_os_type IS '操作系统';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_app_version IS 'APP版本';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_ip_address IS 'IP地址';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_network_type IS '网络类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_is_real_name IS '是否实名';
COMMENT ON COLUMN slord.dwb_user_behavior_f.user_verify_status IS '认证状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_id IS '行为ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_time IS '行为时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_date IS '行为日期';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_hour IS '行为小时';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_weekday IS '行为星期';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_month IS '行为月份';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_quarter IS '行为季度';
COMMENT ON COLUMN slord.dwb_user_behavior_f.behavior_year IS '行为年份';
COMMENT ON COLUMN slord.dwb_user_behavior_f.is_weekend IS '是否周末';
COMMENT ON COLUMN slord.dwb_user_behavior_f.time_period IS '时间段';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_id IS '订单ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_no IS '订单编号';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_status IS '订单状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_status_name IS '订单状态名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_amount IS '订单金额';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_discount_amount IS '优惠金额';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_actual_amount IS '实付金额';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_payment_method IS '支付方式';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_payment_time IS '支付时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_shipping_fee IS '运费';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_product_count IS '商品数量';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_sku_count IS 'SKU数量';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_is_first_order IS '是否首单';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_coupon_id IS '优惠券ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_coupon_name IS '优惠券名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_points_used IS '使用积分';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_points_earned IS '获得积分';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_complete_time IS '完成时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_cancel_time IS '取消时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_cancel_reason IS '取消原因';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_merchant_id IS '商家ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_merchant_name IS '商家名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_delivery_type IS '配送方式';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_delivery_time IS '配送时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_receive_time IS '收货时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_receive_status IS '收货状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_order_source IS '订单来源';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_remark IS '订单备注';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_invoice_type IS '发票类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.order_invoice_title IS '发票抬头';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_product_id IS '商品ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_product_name IS '商品名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_product_code IS '商品编码';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_sku_id IS 'SKU_ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_sku_name IS 'SKU名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_brand_id IS '品牌ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_brand_name IS '品牌名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_category_id IS '类目ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_category_name IS '类目名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_category_level1 IS '一级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_category_level2 IS '二级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_category_level3 IS '三级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_price IS '商品价格';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_cost_price IS '成本价';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_profit_rate IS '利润率';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_stock_status IS '库存状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_sale_status IS '销售状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_product_type IS '商品类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_is_virtual IS '是否虚拟商品';
COMMENT ON COLUMN slord.dwb_user_behavior_f.prod_supplier_id IS '供应商ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_interaction_id IS '互动ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_id IS '内容ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_interaction_type IS '互动类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_interaction_type_name IS '互动类型名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_duration_seconds IS '浏览时长(秒)';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_duration_minutes IS '浏览时长(分)';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_comment_content IS '评论内容';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_comment_word_count IS '评论字数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_share_platform IS '分享平台';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_share_count IS '分享次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_like_count IS '点赞数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_comment_count IS '评论数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_collect_count IS '收藏数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_forward_count IS '转发数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_is_original IS '是否原创';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_source_type IS '来源类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_browse_depth IS '浏览深度';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_scroll_percentage IS '滚动百分比';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_click_count IS '点击次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_stay_time IS '停留时长';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_bounce_flag IS '是否跳出';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_exit_page IS '退出页面';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_session_id IS '会话ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_page_view_count IS '页面浏览数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_unique_visitor IS '独立访客标识';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_referer_url IS '来源URL';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_utm_source IS 'UTM来源';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_utm_medium IS 'UTM媒介';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_utm_campaign IS 'UTM活动';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_interaction_device IS '互动设备';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_title IS '内容标题';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_type IS '内容类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_category IS '内容分类';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_author_id IS '作者ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_author_name IS '作者名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_publish_time IS '发布时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_publish_date IS '发布日期';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_length IS '内容长度';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_word_count IS '字数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_read_count IS '阅读数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_like_count IS '内容点赞数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_comment_count IS '内容评论数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_share_count IS '内容分享数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_collect_count IS '内容收藏数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_topic_id IS '话题ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_topic_name IS '话题名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_is_hot IS '是否热门';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_is_recommend IS '是否推荐';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_status IS '内容状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.content_content_score IS '内容评分';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_relation_id IS '关系ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_target_user_id IS '目标用户ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_relation_type IS '关系类型';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_relation_type_name IS '关系类型名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_is_mutual IS '是否互相关注';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_interaction_count IS '互动次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_last_interaction_time IS '最后互动时间';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_relation_status IS '关系状态';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_source IS '来源';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_group_id IS '分组ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_group_name IS '分组名称';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_remark IS '备注名';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_intimacy_level IS '亲密度等级';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_chat_count IS '聊天次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_call_count IS '通话次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_video_call_count IS '视频通话次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_gift_count IS '礼物次数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_follow_days IS '关注天数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_interaction_frequency IS '互动频率';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_common_friends IS '共同好友数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_common_groups IS '共同群组数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_social_distance IS '社交距离';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_relationship_strength IS '关系强度';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_trust_level IS '信任等级';
COMMENT ON COLUMN slord.dwb_user_behavior_f.social_contact_importance IS '联系人重要性';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_avatar_url IS '头像URL';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_profession IS '职业';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_education IS '学历';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_interests IS '兴趣标签';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_active_level IS '活跃等级';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_influence_score IS '影响力分数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_social_value IS '社交价值';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_user_tags IS '用户标签';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_fans_count IS '粉丝数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_follow_count IS '关注数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_friend_count IS '好友数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_social_activity_score IS '社交活跃度';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_content_creation_score IS '内容创作力';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_engagement_score IS '参与度分数';
COMMENT ON COLUMN slord.dwb_user_behavior_f.profile_social_influence_rank IS '社交影响力排名';
COMMENT ON COLUMN slord.dwb_user_behavior_f.del_flag IS '删除标识';
COMMENT ON COLUMN slord.dwb_user_behavior_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.dw_last_update_date IS '数仓最后更新时间';
