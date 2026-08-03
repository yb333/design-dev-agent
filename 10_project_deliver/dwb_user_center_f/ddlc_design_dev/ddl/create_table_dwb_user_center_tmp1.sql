/* =====================================================
   表名: slusr.dwb_user_center_tmp1
   规则: R0001 - 用户基础属性中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 以 dim_user_f 为主表，LEFT JOIN 等级/地区/来源维度，产出用户基础属性宽表，供最终装配规则引用。粒度不变（一行一用户）。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_tmp1 (
    user_id           bigint,  /* 用户ID */
    user_name         varchar(100),  /* 用户姓名 */
    user_phone_masked varchar(20),  /* 手机号(脱敏) */
    gender_name       varchar(10),  /* 性别 */
    birthday          date,  /* 出生日期 */
    age               int,  /* 年龄 */
    register_time     datetime,  /* 注册时间 */
    register_days     int,  /* 注册天数 */
    last_login_time   datetime,  /* 最近登录时间 */
    level_id          int,  /* 等级ID */
    level_name        varchar(50),  /* 等级名称 */
    level_min_points  int,  /* 等级所需积分 */
    province_code     varchar(20),  /* 省份编码 */
    province_name     varchar(50),  /* 省份名称 */
    city_code         varchar(20),  /* 城市编码 */
    city_name         varchar(50),  /* 城市名称 */
    source_name       varchar(50),  /* 注册来源 */
    member_points     int,  /* 会员积分 */
    member_balance    decimal(18,2),  /* 会员余额 */
    user_status_name  varchar(20),  /* 用户状态 */
    /* 审计字段 */
    del_flag          NVARCHAR(1),
    crt_cycle_id      BIGINT,
    last_upd_cycle_id BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_tmp1 IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_tmp1.user_id IS '用户ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.user_name IS '用户姓名';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.gender_name IS '性别';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.age IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.register_days IS '注册天数';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.last_login_time IS '最近登录时间';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.level_min_points IS '等级所需积分';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.province_code IS '省份编码';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.city_code IS '城市编码';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.source_name IS '注册来源';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.member_balance IS '会员余额';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.user_status_name IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp1.dw_last_update_date IS '数仓最后更新时间';
