/* =====================================================
   表名: slord.dwb_order_center_f
   规则: R0003 - 订单中心宽表装配
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 以 dwd_order_f 为驱动表，LEFT JOIN 订单明细/支付/物流/优惠券/退款事实表（各取一条有效记录）+ 全部维表 + tmp1用户画像 + tmp2商品画像，一次性装配宽表全部字段
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_f (
    order_id               bigint,
    order_no               varchar(64),
    order_status           varchar(20),
    order_status_name      varchar(50),
    order_time             datetime,
    total_amount           decimal(18,2),
    product_amount         decimal(18,2),
    pay_amount             decimal(18,2),
    discount_amount        decimal(18,2),
    freight_amount         decimal(18,2),
    product_cnt            int,
    product_qty            int,
    order_source_name      varchar(50),
    order_type_name        varchar(50),
    order_remark           varchar(500),
    order_date             date,
    user_id                bigint,
    user_name              varchar(100),
    user_phone_masked      varchar(20),
    user_email_masked      varchar(100),
    gender_name            varchar(10),
    user_birthday          date,
    user_age               int,
    user_register_time     datetime,
    user_level_id          int,
    user_level_name        varchar(50),
    member_points          int,
    member_balance         decimal(18,2),
    user_tag               varchar(500),
    user_source_name       varchar(50),
    user_province_code     varchar(20),
    user_city_code         varchar(20),
    user_days              int,
    product_id             bigint,
    product_name           varchar(200),
    product_code           varchar(50),
    sku_code               varchar(50),
    category_l1_id         bigint,
    category_l1_name       varchar(100),
    category_l2_id         bigint,
    category_l2_name       varchar(100),
    category_l3_id         bigint,
    category_l3_name       varchar(100),
    brand_id               bigint,
    brand_name             varchar(100),
    brand_origin           varchar(50),
    product_attr           varchar(500),
    product_spec           varchar(200),
    product_weight         decimal(10,2),
    product_volume         decimal(10,4),
    cost_price             decimal(18,2),
    sale_price             decimal(18,2),
    real_price             decimal(18,2),
    product_tag            varchar(200),
    product_status_name    varchar(20),
    product_profit         decimal(18,2),
    shop_id                bigint,
    shop_name              varchar(200),
    shop_type_name         varchar(50),
    shop_level_name        varchar(20),
    shop_score             decimal(3,2),
    company_name           varchar(200),
    shop_province_code     varchar(20),
    shop_province_name     varchar(50),
    shop_city_code         varchar(20),
    shop_city_name         varchar(50),
    shop_open_time         datetime,
    shop_history_order_cnt int,
    receiver_name          varchar(100),
    receiver_phone_masked  varchar(20),
    receiver_province_code varchar(20),
    receiver_province_name varchar(50),
    receiver_city_code     varchar(20),
    receiver_city_name     varchar(50),
    receiver_district_code varchar(20),
    receiver_district_name varchar(50),
    receiver_street        varchar(200),
    receiver_address       varchar(500),
    full_address           varchar(1000),
    postal_code            varchar(10),
    address_tag_name       varchar(50),
    longitude              decimal(10,6),
    latitude               decimal(10,6),
    pay_time               datetime,
    pay_id                 bigint,
    pay_no                 varchar(64),
    pay_method_code        varchar(20),
    pay_method_name        varchar(50),
    pay_channel_name       varchar(50),
    pay_status_name        varchar(20),
    bank_card_masked       varchar(20),
    bank_name              varchar(50),
    installment_num        int,
    pay_service_fee        decimal(10,2),
    pay_duration_minutes   int,
    ship_time              datetime,
    receive_time           datetime,
    delivery_days          int,
    logistics_id           bigint,
    logistics_no           varchar(50),
    logistics_company_code varchar(20),
    logistics_company_name varchar(100),
    logistics_type_name    varchar(50),
    warehouse_id           bigint,
    warehouse_name         varchar(100),
    warehouse_address      varchar(200),
    logistics_status_name  varchar(50),
    pickup_time            datetime,
    sign_receiver_name     varchar(100),
    ship_duration_hours    int,
    coupon_id              bigint,
    coupon_name            varchar(100),
    coupon_type_name       varchar(50),
    coupon_amount          decimal(10,2),
    activity_id            bigint,
    activity_name          varchar(100),
    activity_type_name     varchar(50),
    activity_discount_rate decimal(5,2),
    full_reduce_amount     decimal(10,2),
    points_deduct_amount   decimal(10,2),
    points_used            int,
    is_marketing_order     varchar(1),
    total_discount_amount  decimal(18,2),
    refund_id              bigint,
    refund_no              varchar(64),
    refund_type_name       varchar(50),
    refund_reason          varchar(200),
    refund_amount          decimal(18,2),
    refund_status_name     varchar(50),
    refund_apply_time      datetime,
    refund_complete_time   datetime,
    is_refund_order        varchar(1),
    del_flag               NVARCHAR(1),
    crt_cycle_id           BIGINT,
    last_upd_cycle_id      BIGINT,
    dw_last_update_date    TIMESTAMP(0)
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_order_center_f IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_f.order_id IS '订单ID';
COMMENT ON COLUMN slord.dwb_order_center_f.order_no IS '订单号';
COMMENT ON COLUMN slord.dwb_order_center_f.order_status IS '订单状态';
COMMENT ON COLUMN slord.dwb_order_center_f.order_status_name IS '订单状态名称';
COMMENT ON COLUMN slord.dwb_order_center_f.order_time IS '下单时间';
COMMENT ON COLUMN slord.dwb_order_center_f.total_amount IS '订单总金额';
COMMENT ON COLUMN slord.dwb_order_center_f.product_amount IS '商品金额';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_amount IS '实付金额';
COMMENT ON COLUMN slord.dwb_order_center_f.discount_amount IS '优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_f.freight_amount IS '运费金额';
COMMENT ON COLUMN slord.dwb_order_center_f.product_cnt IS '商品种类数';
COMMENT ON COLUMN slord.dwb_order_center_f.product_qty IS '商品总件数';
COMMENT ON COLUMN slord.dwb_order_center_f.order_source_name IS '订单来源';
COMMENT ON COLUMN slord.dwb_order_center_f.order_type_name IS '订单类型';
COMMENT ON COLUMN slord.dwb_order_center_f.order_remark IS '订单备注';
COMMENT ON COLUMN slord.dwb_order_center_f.order_date IS '下单日期';
COMMENT ON COLUMN slord.dwb_order_center_f.user_id IS '用户ID';
COMMENT ON COLUMN slord.dwb_order_center_f.user_name IS '用户姓名';
COMMENT ON COLUMN slord.dwb_order_center_f.user_phone_masked IS '用户手机(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_f.user_email_masked IS '用户邮箱(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_f.gender_name IS '用户性别';
COMMENT ON COLUMN slord.dwb_order_center_f.user_birthday IS '用户生日';
COMMENT ON COLUMN slord.dwb_order_center_f.user_age IS '用户年龄';
COMMENT ON COLUMN slord.dwb_order_center_f.user_register_time IS '注册时间';
COMMENT ON COLUMN slord.dwb_order_center_f.user_level_id IS '用户等级ID';
COMMENT ON COLUMN slord.dwb_order_center_f.user_level_name IS '用户等级名称';
COMMENT ON COLUMN slord.dwb_order_center_f.member_points IS '会员积分';
COMMENT ON COLUMN slord.dwb_order_center_f.member_balance IS '会员余额';
COMMENT ON COLUMN slord.dwb_order_center_f.user_tag IS '用户标签';
COMMENT ON COLUMN slord.dwb_order_center_f.user_source_name IS '用户来源';
COMMENT ON COLUMN slord.dwb_order_center_f.user_province_code IS '用户省份编码';
COMMENT ON COLUMN slord.dwb_order_center_f.user_city_code IS '用户城市编码';
COMMENT ON COLUMN slord.dwb_order_center_f.user_days IS '用户注册天数';
COMMENT ON COLUMN slord.dwb_order_center_f.product_id IS '商品ID';
COMMENT ON COLUMN slord.dwb_order_center_f.product_name IS '商品名称';
COMMENT ON COLUMN slord.dwb_order_center_f.product_code IS '商品编码';
COMMENT ON COLUMN slord.dwb_order_center_f.sku_code IS 'SKU编码';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l1_id IS '一级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l1_name IS '一级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l2_id IS '二级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l2_name IS '二级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l3_id IS '三级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_f.category_l3_name IS '三级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_f.brand_id IS '品牌ID';
COMMENT ON COLUMN slord.dwb_order_center_f.brand_name IS '品牌名称';
COMMENT ON COLUMN slord.dwb_order_center_f.brand_origin IS '品牌产地';
COMMENT ON COLUMN slord.dwb_order_center_f.product_attr IS '商品属性';
COMMENT ON COLUMN slord.dwb_order_center_f.product_spec IS '商品规格';
COMMENT ON COLUMN slord.dwb_order_center_f.product_weight IS '商品重量(kg)';
COMMENT ON COLUMN slord.dwb_order_center_f.product_volume IS '商品体积(m³)';
COMMENT ON COLUMN slord.dwb_order_center_f.cost_price IS '商品成本价';
COMMENT ON COLUMN slord.dwb_order_center_f.sale_price IS '商品售价';
COMMENT ON COLUMN slord.dwb_order_center_f.real_price IS '商品实付单价';
COMMENT ON COLUMN slord.dwb_order_center_f.product_tag IS '商品标签';
COMMENT ON COLUMN slord.dwb_order_center_f.product_status_name IS '商品状态';
COMMENT ON COLUMN slord.dwb_order_center_f.product_profit IS '单品毛利';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_id IS '店铺ID';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_name IS '店铺名称';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_type_name IS '店铺类型';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_level_name IS '店铺等级';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_score IS '店铺评分';
COMMENT ON COLUMN slord.dwb_order_center_f.company_name IS '店铺所属公司';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_province_code IS '店铺省份编码';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_province_name IS '店铺省份名称';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_city_code IS '店铺城市编码';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_city_name IS '店铺城市名称';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_open_time IS '开店时间';
COMMENT ON COLUMN slord.dwb_order_center_f.shop_history_order_cnt IS '店铺历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_name IS '收货人姓名';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_phone_masked IS '收货人手机(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_province_code IS '收货省份编码';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_province_name IS '收货省份名称';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_city_code IS '收货城市编码';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_city_name IS '收货城市名称';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_district_code IS '收货区县编码';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_district_name IS '收货区县名称';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_street IS '收货街道';
COMMENT ON COLUMN slord.dwb_order_center_f.receiver_address IS '详细地址';
COMMENT ON COLUMN slord.dwb_order_center_f.full_address IS '完整收货地址';
COMMENT ON COLUMN slord.dwb_order_center_f.postal_code IS '邮政编码';
COMMENT ON COLUMN slord.dwb_order_center_f.address_tag_name IS '地址标签';
COMMENT ON COLUMN slord.dwb_order_center_f.longitude IS '经度';
COMMENT ON COLUMN slord.dwb_order_center_f.latitude IS '纬度';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_time IS '支付时间';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_id IS '支付ID';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_no IS '支付流水号';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_method_code IS '支付方式编码';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_method_name IS '支付方式名称';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_channel_name IS '支付渠道名称';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_status_name IS '支付状态';
COMMENT ON COLUMN slord.dwb_order_center_f.bank_card_masked IS '银行卡号(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_f.bank_name IS '支付银行';
COMMENT ON COLUMN slord.dwb_order_center_f.installment_num IS '分期期数';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_service_fee IS '支付手续费';
COMMENT ON COLUMN slord.dwb_order_center_f.pay_duration_minutes IS '下单到支付时长(分钟)';
COMMENT ON COLUMN slord.dwb_order_center_f.ship_time IS '发货时间';
COMMENT ON COLUMN slord.dwb_order_center_f.receive_time IS '签收时间';
COMMENT ON COLUMN slord.dwb_order_center_f.delivery_days IS '物流时长(天)';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_id IS '物流ID';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_no IS '物流单号';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_company_code IS '物流公司编码';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_company_name IS '物流公司名称';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_type_name IS '物流类型';
COMMENT ON COLUMN slord.dwb_order_center_f.warehouse_id IS '发货仓库ID';
COMMENT ON COLUMN slord.dwb_order_center_f.warehouse_name IS '发货仓库名称';
COMMENT ON COLUMN slord.dwb_order_center_f.warehouse_address IS '发货仓库地址';
COMMENT ON COLUMN slord.dwb_order_center_f.logistics_status_name IS '物流状态';
COMMENT ON COLUMN slord.dwb_order_center_f.pickup_time IS '揽收时间';
COMMENT ON COLUMN slord.dwb_order_center_f.sign_receiver_name IS '签收人';
COMMENT ON COLUMN slord.dwb_order_center_f.ship_duration_hours IS '支付到发货时长(小时)';
COMMENT ON COLUMN slord.dwb_order_center_f.coupon_id IS '优惠券ID';
COMMENT ON COLUMN slord.dwb_order_center_f.coupon_name IS '优惠券名称';
COMMENT ON COLUMN slord.dwb_order_center_f.coupon_type_name IS '优惠券类型';
COMMENT ON COLUMN slord.dwb_order_center_f.coupon_amount IS '优惠券金额';
COMMENT ON COLUMN slord.dwb_order_center_f.activity_id IS '活动ID';
COMMENT ON COLUMN slord.dwb_order_center_f.activity_name IS '活动名称';
COMMENT ON COLUMN slord.dwb_order_center_f.activity_type_name IS '活动类型';
COMMENT ON COLUMN slord.dwb_order_center_f.activity_discount_rate IS '活动折扣率(%)';
COMMENT ON COLUMN slord.dwb_order_center_f.full_reduce_amount IS '满减金额';
COMMENT ON COLUMN slord.dwb_order_center_f.points_deduct_amount IS '积分抵扣金额';
COMMENT ON COLUMN slord.dwb_order_center_f.points_used IS '使用积分数';
COMMENT ON COLUMN slord.dwb_order_center_f.is_marketing_order IS '是否营销订单';
COMMENT ON COLUMN slord.dwb_order_center_f.total_discount_amount IS '总优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_id IS '退款ID';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_no IS '退款单号';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_type_name IS '退款类型';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_reason IS '退款原因';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_amount IS '退款金额';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_status_name IS '退款状态';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_apply_time IS '退款申请时间';
COMMENT ON COLUMN slord.dwb_order_center_f.refund_complete_time IS '退款完成时间';
COMMENT ON COLUMN slord.dwb_order_center_f.is_refund_order IS '是否退款订单';
COMMENT ON COLUMN slord.dwb_order_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slord.dwb_order_center_f.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN slord.dwb_order_center_f.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN slord.dwb_order_center_f.dw_last_update_date IS '更新时间';
