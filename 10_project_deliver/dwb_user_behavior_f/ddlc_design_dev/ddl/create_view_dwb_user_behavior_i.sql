/* I视图: slord.dwb_user_behavior_i（用户行为宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slord.dwb_user_behavior_i AS
SELECT
    behavior_id,
    behavior_time,
    behavior_date,
    behavior_hour,
    behavior_weekday,
    behavior_month,
    behavior_quarter,
    behavior_year,
    is_weekend,
    time_period,
    user_user_id,
    user_user_name,
    user_user_phone,
    user_gender,
    user_age,
    user_birthday,
    user_province_name,
    user_city_name,
    user_user_level,
    user_user_level_name,
    user_vip_status,
    user_register_time,
    user_register_date,
    user_user_status,
    user_user_status_name,
    user_source_channel,
    user_source_type,
    user_first_active_time,
    user_last_active_time,
    user_active_days,
    user_total_score,
    user_credit_score,
    user_risk_level,
    user_device_type,
    user_os_type,
    user_app_version,
    user_ip_address,
    user_network_type,
    user_is_real_name,
    user_verify_status,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slord.dwb_user_behavior_f;

COMMENT ON TABLE slord.dwb_user_behavior_i IS '用户行为宽表（视图）';

COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_id IS '行为ID';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_time IS '行为时间';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_date IS '行为日期';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_hour IS '行为小时';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_weekday IS '行为星期';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_month IS '行为月份';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_quarter IS '行为季度';
COMMENT ON COLUMN slord.dwb_user_behavior_i.behavior_year IS '行为年份';
COMMENT ON COLUMN slord.dwb_user_behavior_i.is_weekend IS '是否周末';
COMMENT ON COLUMN slord.dwb_user_behavior_i.time_period IS '时间段';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_id IS '用户ID';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_name IS '用户姓名';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_phone IS '手机号';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_gender IS '性别';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_age IS '年龄';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_birthday IS '出生日期';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_province_name IS '省份';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_city_name IS '城市';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_level IS '用户等级';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_level_name IS '用户等级名称';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_vip_status IS 'VIP状态';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_register_time IS '注册时间';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_register_date IS '注册日期';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_status IS '用户状态';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_user_status_name IS '用户状态名称';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_source_channel IS '来源渠道';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_source_type IS '来源类型';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_first_active_time IS '首次活跃时间';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_last_active_time IS '最后活跃时间';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_active_days IS '活跃天数';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_total_score IS '总积分';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_credit_score IS '信用分';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_risk_level IS '风险等级';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_device_type IS '设备类型';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_os_type IS '操作系统';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_app_version IS 'APP版本';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_ip_address IS 'IP地址';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_network_type IS '网络类型';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_is_real_name IS '是否实名';
COMMENT ON COLUMN slord.dwb_user_behavior_i.user_verify_status IS '认证状态';
COMMENT ON COLUMN slord.dwb_user_behavior_i.del_flag IS '删除标识';
COMMENT ON COLUMN slord.dwb_user_behavior_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_i.dw_last_update_date IS '数仓最后更新时间';
