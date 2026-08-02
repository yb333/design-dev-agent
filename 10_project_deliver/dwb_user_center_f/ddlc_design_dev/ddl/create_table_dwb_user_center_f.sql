/* =====================================================
   表名: slusr.dwb_user_center_f
   规则: R0004 - 用户中心宽表组装
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 以用户维度为主表，关联等级/地区/来源维度及三张画像中间表，装配全部用户中心宽表字段（直取+加工+派生+RFM打分+审计）
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_f (
    user_id             bigint,  /* 用户ID */
    user_name           varchar(100),  /* 用户姓名 */
    birthday            date,  /* 出生日期 */
    register_time       datetime,  /* 注册时间 */
    last_login_time     datetime,  /* 最近登录时间 */
    level_id            int,  /* 等级ID */
    level_name          varchar(50),  /* 等级名称 */
    level_min_points    int,  /* 等级所需积分 */
    province_code       varchar(20),  /* 省份编码 */
    province_name       varchar(50),  /* 省份名称 */
    city_code           varchar(20),  /* 城市编码 */
    source_name         varchar(50),  /* 注册来源 */
    member_points       int,  /* 会员积分 */
    member_balance      decimal(18,2),  /* 会员余额 */
    user_phone_masked   varchar(20),  /* 手机号(脱敏) */
    gender_name         varchar(10),  /* 性别 */
    age                 int,  /* 年龄 */
    register_days       int,  /* 注册天数 */
    user_status_name    varchar(20),  /* 用户状态 */
    city_name           varchar(50),  /* 城市名称 */
    avg_order_amount    decimal(18,2),  /* 平均客单价 */
    pv_to_order_rate    decimal(5,2),  /* 浏览-下单转化率(%) */
    pv_to_cart_rate     decimal(5,2),  /* 浏览-加购转化率(%) */
    refund_rate         decimal(5,2),  /* 退款率(%) */
    order_freq_label    varchar(20),  /* 下单频率标签 */
    consume_level_label varchar(20),  /* 消费能力标签 */
    rfm_r_score         int,  /* RFM-R值 */
    rfm_f_score         int,  /* RFM-F值 */
    rfm_m_score         int,  /* RFM-M值 */
    rfm_segment         varchar(20),  /* 用户价值分层 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE,  /* 数仓最后更新时间 */
    /* 审计字段 */
    del_flag            NVARCHAR(1),
    crt_cycle_id        BIGINT,
    last_upd_cycle_id   BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_f IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_f.user_id IS '用户ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.user_name IS '用户姓名';
COMMENT ON COLUMN slusr.dwb_user_center_f.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_center_f.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_login_time IS '最近登录时间';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_min_points IS '等级所需积分';
COMMENT ON COLUMN slusr.dwb_user_center_f.province_code IS '省份编码';
COMMENT ON COLUMN slusr.dwb_user_center_f.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.city_code IS '城市编码';
COMMENT ON COLUMN slusr.dwb_user_center_f.source_name IS '注册来源';
COMMENT ON COLUMN slusr.dwb_user_center_f.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_center_f.member_balance IS '会员余额';
COMMENT ON COLUMN slusr.dwb_user_center_f.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_center_f.gender_name IS '性别';
COMMENT ON COLUMN slusr.dwb_user_center_f.age IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_center_f.register_days IS '注册天数';
COMMENT ON COLUMN slusr.dwb_user_center_f.user_status_name IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_center_f.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.avg_order_amount IS '平均客单价';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_order_rate IS '浏览-下单转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_cart_rate IS '浏览-加购转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.refund_rate IS '退款率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.order_freq_label IS '下单频率标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.consume_level_label IS '消费能力标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_r_score IS 'RFM-R值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_f_score IS 'RFM-F值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_m_score IS 'RFM-M值';
COMMENT ON COLUMN slusr.dwb_user_center_f.rfm_segment IS '用户价值分层';
COMMENT ON COLUMN slusr.dwb_user_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.dw_last_update_date IS '数仓最后更新时间';
COMMENT ON COLUMN slusr.dwb_user_center_f.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.dw_last_update_date IS '数仓最后更新时间';
