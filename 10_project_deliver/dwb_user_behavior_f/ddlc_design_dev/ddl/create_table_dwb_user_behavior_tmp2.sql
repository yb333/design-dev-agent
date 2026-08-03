/* =====================================================
   表名: slord.dwb_user_behavior_tmp2
   规则: R0002 - 内容互动场景加工
   分布键: behavior_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 从内容互动表 ods_content_interaction_f 出发, LEFT JOIN 内容维度 dim_content_d 取内容属性, 加工内容互动场景的行为明细(互动+内容共50字段), 产出到场景中间表 tmp2 供 F 表 UNION 合并
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_user_behavior_tmp2 (
    content_interaction_id        bigint,  /* 互动ID */
    content_content_id            bigint,  /* 内容ID */
    content_interaction_type      varchar(50),  /* 互动类型 */
    content_interaction_type_name varchar(50),  /* 互动类型名称 */
    content_duration_seconds      int,  /* 浏览时长(秒) */
    content_duration_minutes      decimal(5,2),  /* 浏览时长(分) */
    content_comment_content       varchar(1000),  /* 评论内容 */
    content_comment_word_count    int,  /* 评论字数 */
    content_share_platform        varchar(50),  /* 分享平台 */
    content_share_count           int,  /* 分享次数 */
    content_like_count            int,  /* 点赞数 */
    content_comment_count         int,  /* 评论数 */
    content_collect_count         int,  /* 收藏数 */
    content_forward_count         int,  /* 转发数 */
    content_is_original           int,  /* 是否原创 */
    content_source_type           varchar(50),  /* 来源类型 */
    content_browse_depth          int,  /* 浏览深度 */
    content_scroll_percentage     decimal(5,2),  /* 滚动百分比 */
    content_click_count           int,  /* 点击次数 */
    content_stay_time             int,  /* 停留时长 */
    content_bounce_flag           int,  /* 是否跳出 */
    content_exit_page             varchar(200),  /* 退出页面 */
    content_session_id            varchar(100),  /* 会话ID */
    content_page_view_count       int,  /* 页面浏览数 */
    content_unique_visitor        int,  /* 独立访客标识 */
    content_referer_url           varchar(500),  /* 来源URL */
    content_utm_source            varchar(100),  /* UTM来源 */
    content_utm_medium            varchar(100),  /* UTM媒介 */
    content_utm_campaign          varchar(100),  /* UTM活动 */
    content_interaction_device    varchar(50),  /* 互动设备 */
    content_content_title         varchar(200),  /* 内容标题 */
    content_content_type          varchar(50),  /* 内容类型 */
    content_content_category      varchar(50),  /* 内容分类 */
    content_author_id             bigint,  /* 作者ID */
    content_author_name           varchar(100),  /* 作者名称 */
    content_publish_time          timestamp,  /* 发布时间 */
    content_publish_date          date,  /* 发布日期 */
    content_content_length        int,  /* 内容长度 */
    content_word_count            int,  /* 字数 */
    content_read_count            int,  /* 阅读数 */
    content_content_like_count    int,  /* 内容点赞数 */
    content_content_comment_count int,  /* 内容评论数 */
    content_content_share_count   int,  /* 内容分享数 */
    content_content_collect_count int,  /* 内容收藏数 */
    content_topic_id              int,  /* 话题ID */
    content_topic_name            varchar(100),  /* 话题名称 */
    content_is_hot                int,  /* 是否热门 */
    content_is_recommend          int,  /* 是否推荐 */
    content_content_status        varchar(20),  /* 内容状态 */
    content_content_score         decimal(5,2),  /* 内容评分 */
    /* 审计字段 */
    del_flag                      NVARCHAR(1),
    crt_cycle_id                  BIGINT,
    last_upd_cycle_id             BIGINT,
    dw_last_update_date           TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(behavior_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_user_behavior_tmp2 IS '用户行为宽表';

COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_interaction_id IS '互动ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_id IS '内容ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_interaction_type IS '互动类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_interaction_type_name IS '互动类型名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_duration_seconds IS '浏览时长(秒)';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_duration_minutes IS '浏览时长(分)';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_comment_content IS '评论内容';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_comment_word_count IS '评论字数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_share_platform IS '分享平台';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_share_count IS '分享次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_like_count IS '点赞数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_comment_count IS '评论数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_collect_count IS '收藏数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_forward_count IS '转发数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_is_original IS '是否原创';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_source_type IS '来源类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_browse_depth IS '浏览深度';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_scroll_percentage IS '滚动百分比';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_click_count IS '点击次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_stay_time IS '停留时长';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_bounce_flag IS '是否跳出';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_exit_page IS '退出页面';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_session_id IS '会话ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_page_view_count IS '页面浏览数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_unique_visitor IS '独立访客标识';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_referer_url IS '来源URL';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_utm_source IS 'UTM来源';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_utm_medium IS 'UTM媒介';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_utm_campaign IS 'UTM活动';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_interaction_device IS '互动设备';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_title IS '内容标题';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_type IS '内容类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_category IS '内容分类';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_author_id IS '作者ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_author_name IS '作者名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_publish_time IS '发布时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_publish_date IS '发布日期';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_length IS '内容长度';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_word_count IS '字数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_read_count IS '阅读数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_like_count IS '内容点赞数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_comment_count IS '内容评论数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_share_count IS '内容分享数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_collect_count IS '内容收藏数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_topic_id IS '话题ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_topic_name IS '话题名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_is_hot IS '是否热门';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_is_recommend IS '是否推荐';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_status IS '内容状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.content_content_score IS '内容评分';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp2.dw_last_update_date IS '数仓最后更新时间';
