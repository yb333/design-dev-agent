/* =====================================================
   表名: slord.dwb_user_behavior_tmp3
   规则: R0003 - 社交关系场景加工
   分布键: behavior_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 从社交关系表 ods_social_relation_f 出发, LEFT JOIN 用户画像维度 dim_user_profile_d 取画像属性, 加工社交关系场景的行为明细(关系+画像共40字段), 产出到场景中间表 tmp3 供 F 表 UNION 合并
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_user_behavior_tmp3 (
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
    /* 审计字段 */
    del_flag                       NVARCHAR(1),
    crt_cycle_id                   BIGINT,
    last_upd_cycle_id              BIGINT,
    dw_last_update_date            TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(behavior_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_user_behavior_tmp3 IS '用户行为宽表';

COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_relation_id IS '关系ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_target_user_id IS '目标用户ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_relation_type IS '关系类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_relation_type_name IS '关系类型名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_is_mutual IS '是否互相关注';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_interaction_count IS '互动次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_last_interaction_time IS '最后互动时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_relation_status IS '关系状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_source IS '来源';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_group_id IS '分组ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_group_name IS '分组名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_remark IS '备注名';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_intimacy_level IS '亲密度等级';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_chat_count IS '聊天次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_call_count IS '通话次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_video_call_count IS '视频通话次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_gift_count IS '礼物次数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_follow_days IS '关注天数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_interaction_frequency IS '互动频率';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_common_friends IS '共同好友数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_common_groups IS '共同群组数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_social_distance IS '社交距离';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_relationship_strength IS '关系强度';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_trust_level IS '信任等级';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.social_contact_importance IS '联系人重要性';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_avatar_url IS '头像URL';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_profession IS '职业';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_education IS '学历';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_interests IS '兴趣标签';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_active_level IS '活跃等级';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_influence_score IS '影响力分数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_social_value IS '社交价值';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_user_tags IS '用户标签';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_fans_count IS '粉丝数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_follow_count IS '关注数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_friend_count IS '好友数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_social_activity_score IS '社交活跃度';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_content_creation_score IS '内容创作力';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_engagement_score IS '参与度分数';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.profile_social_influence_rank IS '社交影响力排名';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp3.dw_last_update_date IS '数仓最后更新时间';
