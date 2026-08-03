/* =====================================================
   表名: slord.dwb_user_behavior_f
   规则: R0004 - F表多场景合并
   分布键: behavior_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 将 3 个场景中间表(tmp1/tmp2/tmp3)UNION ALL 合并写入 F 表 dwb_user_behavior_f; 同时承载 3 场景共用字段(behavior_* 时间派生/is_weekend/time_period/user_* 用户维度/4 审计字段); 时间派生和用户脱敏的 design_logic 在此登记一次, coder 阶段在 3 个场景 SQL 里复用; 配套由 coder 生成 I 视图 dwb_user_behavior_i (SELECT * FROM F 表)
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_user_behavior_f (
    behavior_id            bigint,  /* 行为ID */
    behavior_time          timestamp,  /* 行为时间 */
    behavior_date          date,  /* 行为日期 */
    behavior_hour          int,  /* 行为小时 */
    behavior_weekday       int,  /* 行为星期 */
    behavior_month         int,  /* 行为月份 */
    behavior_quarter       int,  /* 行为季度 */
    behavior_year          int,  /* 行为年份 */
    is_weekend             int,  /* 是否周末 */
    time_period            varchar(20),  /* 时间段 */
    user_user_id           bigint,  /* 用户ID */
    user_user_name         varchar(100),  /* 用户姓名 */
    user_user_phone        varchar(20),  /* 手机号 */
    user_gender            varchar(10),  /* 性别 */
    user_age               int,  /* 年龄 */
    user_birthday          date,  /* 出生日期 */
    user_province_name     varchar(50),  /* 省份 */
    user_city_name         varchar(50),  /* 城市 */
    user_user_level        int,  /* 用户等级 */
    user_user_level_name   varchar(50),  /* 用户等级名称 */
    user_vip_status        int,  /* VIP状态 */
    user_register_time     timestamp,  /* 注册时间 */
    user_register_date     date,  /* 注册日期 */
    user_user_status       varchar(20),  /* 用户状态 */
    user_user_status_name  varchar(50),  /* 用户状态名称 */
    user_source_channel    varchar(50),  /* 来源渠道 */
    user_source_type       varchar(50),  /* 来源类型 */
    user_first_active_time timestamp,  /* 首次活跃时间 */
    user_last_active_time  timestamp,  /* 最后活跃时间 */
    user_active_days       int,  /* 活跃天数 */
    user_total_score       int,  /* 总积分 */
    user_credit_score      int,  /* 信用分 */
    user_risk_level        varchar(20),  /* 风险等级 */
    user_device_type       varchar(50),  /* 设备类型 */
    user_os_type           varchar(50),  /* 操作系统 */
    user_app_version       varchar(20),  /* APP版本 */
    user_ip_address        varchar(50),  /* IP地址 */
    user_network_type      varchar(20),  /* 网络类型 */
    user_is_real_name      int,  /* 是否实名 */
    user_verify_status     varchar(20),  /* 认证状态 */
    del_flag               NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id           BIGINT,  /* 创建批次ID */
    last_upd_cycle_id      BIGINT,  /* 最后更新批次ID */
    dw_last_update_date    TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(behavior_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_user_behavior_f IS '用户行为宽表';

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
COMMENT ON COLUMN slord.dwb_user_behavior_f.del_flag IS '删除标识';
COMMENT ON COLUMN slord.dwb_user_behavior_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_f.dw_last_update_date IS '数仓最后更新时间';
