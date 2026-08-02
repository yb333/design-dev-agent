/* =====================================================
   表名: slusr.dwb_user_center_f
   规则: R0003 - 用户中心宽表装配
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 以 dim_user_f 为主表左联维度表与中间表，CTE 聚合行为/优惠/退款/购物车事实，计算派生转化率与标签，产出最终宽表
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_f (
    user_id             bigint,  /* 用户ID */
    user_name           varchar(100),  /* 用户姓名 */
    user_phone_masked   varchar(20),  /* 手机号(脱敏) */
    gender_name         varchar(10),  /* 性别 */
    birthday            date,  /* 出生日期 */
    age                 int,  /* 年龄 */
    register_time       datetime,  /* 注册时间 */
    register_days       int,  /* 注册天数 */
    last_login_time     datetime,  /* 最近登录时间 */
    level_id            int,  /* 等级ID */
    level_name          varchar(50),  /* 等级名称 */
    level_min_points    int,  /* 等级所需积分 */
    province_code       varchar(20),  /* 省份编码 */
    province_name       varchar(50),  /* 省份名称 */
    city_code           varchar(20),  /* 城市编码 */
    city_name           varchar(50),  /* 城市名称 */
    source_name         varchar(50),  /* 注册来源 */
    member_points       int,  /* 会员积分 */
    member_balance      decimal(18,2),  /* 会员余额 */
    user_status_name    varchar(20),  /* 用户状态 */
    total_pv_cnt        int,  /* 浏览次数 */
    total_collect_cnt   int,  /* 收藏次数 */
    total_cart_cnt      int,  /* 加购次数 */
    pv_to_order_rate    decimal(5,2),  /* 浏览-下单转化率(%) */
    pv_to_cart_rate     decimal(5,2),  /* 浏览-加购转化率(%) */
    coupon_used_cnt     int,  /* 优惠券使用次数 */
    coupon_total_amount decimal(18,2),  /* 优惠券使用金额 */
    refund_cnt          int,  /* 退款次数 */
    refund_rate         decimal(5,2),  /* 退款率(%) */
    cart_product_cnt    int,  /* 购物车商品数 */
    cart_total_amount   decimal(18,2),  /* 购物车金额 */
    order_freq_label    varchar(20),  /* 下单频率标签 */
    consume_level_label varchar(20),  /* 消费能力标签 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
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
COMMENT ON COLUMN slusr.dwb_user_center_f.user_phone_masked IS '手机号(脱敏)';
COMMENT ON COLUMN slusr.dwb_user_center_f.gender_name IS '性别';
COMMENT ON COLUMN slusr.dwb_user_center_f.birthday IS '出生日期';
COMMENT ON COLUMN slusr.dwb_user_center_f.age IS '年龄';
COMMENT ON COLUMN slusr.dwb_user_center_f.register_time IS '注册时间';
COMMENT ON COLUMN slusr.dwb_user_center_f.register_days IS '注册天数';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_login_time IS '最近登录时间';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_id IS '等级ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_name IS '等级名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.level_min_points IS '等级所需积分';
COMMENT ON COLUMN slusr.dwb_user_center_f.province_code IS '省份编码';
COMMENT ON COLUMN slusr.dwb_user_center_f.province_name IS '省份名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.city_code IS '城市编码';
COMMENT ON COLUMN slusr.dwb_user_center_f.city_name IS '城市名称';
COMMENT ON COLUMN slusr.dwb_user_center_f.source_name IS '注册来源';
COMMENT ON COLUMN slusr.dwb_user_center_f.member_points IS '会员积分';
COMMENT ON COLUMN slusr.dwb_user_center_f.member_balance IS '会员余额';
COMMENT ON COLUMN slusr.dwb_user_center_f.user_status_name IS '用户状态';
COMMENT ON COLUMN slusr.dwb_user_center_f.total_pv_cnt IS '浏览次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.total_collect_cnt IS '收藏次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.total_cart_cnt IS '加购次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_order_rate IS '浏览-下单转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.pv_to_cart_rate IS '浏览-加购转化率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.coupon_used_cnt IS '优惠券使用次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.coupon_total_amount IS '优惠券使用金额';
COMMENT ON COLUMN slusr.dwb_user_center_f.refund_cnt IS '退款次数';
COMMENT ON COLUMN slusr.dwb_user_center_f.refund_rate IS '退款率(%)';
COMMENT ON COLUMN slusr.dwb_user_center_f.cart_product_cnt IS '购物车商品数';
COMMENT ON COLUMN slusr.dwb_user_center_f.cart_total_amount IS '购物车金额';
COMMENT ON COLUMN slusr.dwb_user_center_f.order_freq_label IS '下单频率标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.consume_level_label IS '消费能力标签';
COMMENT ON COLUMN slusr.dwb_user_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slusr.dwb_user_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f.dw_last_update_date IS '数仓最后更新时间';
