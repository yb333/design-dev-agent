/* I视图: slord.dwb_order_center_i（订单中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slord.dwb_order_center_i AS
SELECT
    order_id,
    order_no,
    order_status,
    order_status_name,
    order_time,
    total_amount,
    product_amount,
    pay_amount,
    discount_amount,
    freight_amount,
    product_cnt,
    product_qty,
    order_source_name,
    order_type_name,
    order_remark,
    order_date,
    user_id,
    user_name,
    user_phone_masked,
    user_email_masked,
    gender_name,
    user_birthday,
    user_age,
    user_register_time,
    user_level_id,
    user_level_name,
    member_points,
    member_balance,
    user_tag,
    user_source_name,
    user_province_code,
    user_city_code,
    user_days,
    product_id,
    product_name,
    product_code,
    sku_code,
    category_l1_id,
    category_l1_name,
    category_l2_id,
    category_l2_name,
    category_l3_id,
    category_l3_name,
    brand_id,
    brand_name,
    brand_origin,
    product_attr,
    product_spec,
    product_weight,
    product_volume,
    cost_price,
    sale_price,
    real_price,
    product_tag,
    product_status_name,
    product_profit,
    shop_id,
    shop_name,
    shop_type_name,
    shop_level_name,
    shop_score,
    company_name,
    shop_province_code,
    shop_province_name,
    shop_city_code,
    shop_city_name,
    shop_open_time,
    shop_history_order_cnt,
    receiver_name,
    receiver_phone_masked,
    receiver_province_code,
    receiver_province_name,
    receiver_city_code,
    receiver_city_name,
    receiver_district_code,
    receiver_district_name,
    receiver_street,
    receiver_address,
    full_address,
    postal_code,
    address_tag_name,
    longitude,
    latitude,
    pay_time,
    pay_id,
    pay_no,
    pay_method_code,
    pay_method_name,
    pay_channel_name,
    pay_status_name,
    bank_card_masked,
    bank_name,
    installment_num,
    pay_service_fee,
    pay_duration_minutes,
    ship_time,
    receive_time,
    delivery_days,
    logistics_id,
    logistics_no,
    logistics_company_code,
    logistics_company_name,
    logistics_type_name,
    warehouse_id,
    warehouse_name,
    warehouse_address,
    logistics_status_name,
    pickup_time,
    sign_receiver_name,
    ship_duration_hours,
    coupon_id,
    coupon_name,
    coupon_type_name,
    coupon_amount,
    activity_id,
    activity_name,
    activity_type_name,
    activity_discount_rate,
    full_reduce_amount,
    points_deduct_amount,
    points_used,
    is_marketing_order,
    total_discount_amount,
    refund_id,
    refund_no,
    refund_type_name,
    refund_reason,
    refund_amount,
    refund_status_name,
    refund_apply_time,
    refund_complete_time,
    is_refund_order,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slord.dwb_order_center_f;

COMMENT ON TABLE slord.dwb_order_center_i IS '订单中心宽表（视图）';

COMMENT ON COLUMN slord.dwb_order_center_i.order_id IS '订单ID';
COMMENT ON COLUMN slord.dwb_order_center_i.order_no IS '订单号';
COMMENT ON COLUMN slord.dwb_order_center_i.order_status IS '订单状态';
COMMENT ON COLUMN slord.dwb_order_center_i.order_status_name IS '订单状态名称';
COMMENT ON COLUMN slord.dwb_order_center_i.order_time IS '下单时间';
COMMENT ON COLUMN slord.dwb_order_center_i.total_amount IS '订单总金额';
COMMENT ON COLUMN slord.dwb_order_center_i.product_amount IS '商品金额';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_amount IS '实付金额';
COMMENT ON COLUMN slord.dwb_order_center_i.discount_amount IS '优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_i.freight_amount IS '运费金额';
COMMENT ON COLUMN slord.dwb_order_center_i.product_cnt IS '商品种类数';
COMMENT ON COLUMN slord.dwb_order_center_i.product_qty IS '商品总件数';
COMMENT ON COLUMN slord.dwb_order_center_i.order_source_name IS '订单来源';
COMMENT ON COLUMN slord.dwb_order_center_i.order_type_name IS '订单类型';
COMMENT ON COLUMN slord.dwb_order_center_i.order_remark IS '订单备注';
COMMENT ON COLUMN slord.dwb_order_center_i.order_date IS '下单日期';
COMMENT ON COLUMN slord.dwb_order_center_i.user_id IS '用户ID';
COMMENT ON COLUMN slord.dwb_order_center_i.user_name IS '用户姓名';
COMMENT ON COLUMN slord.dwb_order_center_i.user_phone_masked IS '用户手机(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_i.user_email_masked IS '用户邮箱(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_i.gender_name IS '用户性别';
COMMENT ON COLUMN slord.dwb_order_center_i.user_birthday IS '用户生日';
COMMENT ON COLUMN slord.dwb_order_center_i.user_age IS '用户年龄';
COMMENT ON COLUMN slord.dwb_order_center_i.user_register_time IS '注册时间';
COMMENT ON COLUMN slord.dwb_order_center_i.user_level_id IS '用户等级ID';
COMMENT ON COLUMN slord.dwb_order_center_i.user_level_name IS '用户等级名称';
COMMENT ON COLUMN slord.dwb_order_center_i.member_points IS '会员积分';
COMMENT ON COLUMN slord.dwb_order_center_i.member_balance IS '会员余额';
COMMENT ON COLUMN slord.dwb_order_center_i.user_tag IS '用户标签';
COMMENT ON COLUMN slord.dwb_order_center_i.user_source_name IS '用户来源';
COMMENT ON COLUMN slord.dwb_order_center_i.user_province_code IS '用户省份编码';
COMMENT ON COLUMN slord.dwb_order_center_i.user_city_code IS '用户城市编码';
COMMENT ON COLUMN slord.dwb_order_center_i.user_days IS '用户注册天数';
COMMENT ON COLUMN slord.dwb_order_center_i.product_id IS '商品ID';
COMMENT ON COLUMN slord.dwb_order_center_i.product_name IS '商品名称';
COMMENT ON COLUMN slord.dwb_order_center_i.product_code IS '商品编码';
COMMENT ON COLUMN slord.dwb_order_center_i.sku_code IS 'SKU编码';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l1_id IS '一级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l1_name IS '一级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l2_id IS '二级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l2_name IS '二级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l3_id IS '三级类目ID';
COMMENT ON COLUMN slord.dwb_order_center_i.category_l3_name IS '三级类目名称';
COMMENT ON COLUMN slord.dwb_order_center_i.brand_id IS '品牌ID';
COMMENT ON COLUMN slord.dwb_order_center_i.brand_name IS '品牌名称';
COMMENT ON COLUMN slord.dwb_order_center_i.brand_origin IS '品牌产地';
COMMENT ON COLUMN slord.dwb_order_center_i.product_attr IS '商品属性';
COMMENT ON COLUMN slord.dwb_order_center_i.product_spec IS '商品规格';
COMMENT ON COLUMN slord.dwb_order_center_i.product_weight IS '商品重量(kg)';
COMMENT ON COLUMN slord.dwb_order_center_i.product_volume IS '商品体积(m³)';
COMMENT ON COLUMN slord.dwb_order_center_i.cost_price IS '商品成本价';
COMMENT ON COLUMN slord.dwb_order_center_i.sale_price IS '商品售价';
COMMENT ON COLUMN slord.dwb_order_center_i.real_price IS '商品实付单价';
COMMENT ON COLUMN slord.dwb_order_center_i.product_tag IS '商品标签';
COMMENT ON COLUMN slord.dwb_order_center_i.product_status_name IS '商品状态';
COMMENT ON COLUMN slord.dwb_order_center_i.product_profit IS '单品毛利';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_id IS '店铺ID';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_name IS '店铺名称';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_type_name IS '店铺类型';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_level_name IS '店铺等级';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_score IS '店铺评分';
COMMENT ON COLUMN slord.dwb_order_center_i.company_name IS '店铺所属公司';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_province_code IS '店铺省份编码';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_province_name IS '店铺省份名称';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_city_code IS '店铺城市编码';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_city_name IS '店铺城市名称';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_open_time IS '开店时间';
COMMENT ON COLUMN slord.dwb_order_center_i.shop_history_order_cnt IS '店铺历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_name IS '收货人姓名';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_phone_masked IS '收货人手机(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_province_code IS '收货省份编码';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_province_name IS '收货省份名称';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_city_code IS '收货城市编码';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_city_name IS '收货城市名称';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_district_code IS '收货区县编码';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_district_name IS '收货区县名称';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_street IS '收货街道';
COMMENT ON COLUMN slord.dwb_order_center_i.receiver_address IS '详细地址';
COMMENT ON COLUMN slord.dwb_order_center_i.full_address IS '完整收货地址';
COMMENT ON COLUMN slord.dwb_order_center_i.postal_code IS '邮政编码';
COMMENT ON COLUMN slord.dwb_order_center_i.address_tag_name IS '地址标签';
COMMENT ON COLUMN slord.dwb_order_center_i.longitude IS '经度';
COMMENT ON COLUMN slord.dwb_order_center_i.latitude IS '纬度';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_time IS '支付时间';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_id IS '支付ID';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_no IS '支付流水号';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_method_code IS '支付方式编码';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_method_name IS '支付方式名称';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_channel_name IS '支付渠道名称';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_status_name IS '支付状态';
COMMENT ON COLUMN slord.dwb_order_center_i.bank_card_masked IS '银行卡号(脱敏)';
COMMENT ON COLUMN slord.dwb_order_center_i.bank_name IS '支付银行';
COMMENT ON COLUMN slord.dwb_order_center_i.installment_num IS '分期期数';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_service_fee IS '支付手续费';
COMMENT ON COLUMN slord.dwb_order_center_i.pay_duration_minutes IS '下单到支付时长(分钟)';
COMMENT ON COLUMN slord.dwb_order_center_i.ship_time IS '发货时间';
COMMENT ON COLUMN slord.dwb_order_center_i.receive_time IS '签收时间';
COMMENT ON COLUMN slord.dwb_order_center_i.delivery_days IS '物流时长(天)';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_id IS '物流ID';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_no IS '物流单号';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_company_code IS '物流公司编码';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_company_name IS '物流公司名称';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_type_name IS '物流类型';
COMMENT ON COLUMN slord.dwb_order_center_i.warehouse_id IS '发货仓库ID';
COMMENT ON COLUMN slord.dwb_order_center_i.warehouse_name IS '发货仓库名称';
COMMENT ON COLUMN slord.dwb_order_center_i.warehouse_address IS '发货仓库地址';
COMMENT ON COLUMN slord.dwb_order_center_i.logistics_status_name IS '物流状态';
COMMENT ON COLUMN slord.dwb_order_center_i.pickup_time IS '揽收时间';
COMMENT ON COLUMN slord.dwb_order_center_i.sign_receiver_name IS '签收人';
COMMENT ON COLUMN slord.dwb_order_center_i.ship_duration_hours IS '支付到发货时长(小时)';
COMMENT ON COLUMN slord.dwb_order_center_i.coupon_id IS '优惠券ID';
COMMENT ON COLUMN slord.dwb_order_center_i.coupon_name IS '优惠券名称';
COMMENT ON COLUMN slord.dwb_order_center_i.coupon_type_name IS '优惠券类型';
COMMENT ON COLUMN slord.dwb_order_center_i.coupon_amount IS '优惠券金额';
COMMENT ON COLUMN slord.dwb_order_center_i.activity_id IS '活动ID';
COMMENT ON COLUMN slord.dwb_order_center_i.activity_name IS '活动名称';
COMMENT ON COLUMN slord.dwb_order_center_i.activity_type_name IS '活动类型';
COMMENT ON COLUMN slord.dwb_order_center_i.activity_discount_rate IS '活动折扣率(%)';
COMMENT ON COLUMN slord.dwb_order_center_i.full_reduce_amount IS '满减金额';
COMMENT ON COLUMN slord.dwb_order_center_i.points_deduct_amount IS '积分抵扣金额';
COMMENT ON COLUMN slord.dwb_order_center_i.points_used IS '使用积分数';
COMMENT ON COLUMN slord.dwb_order_center_i.is_marketing_order IS '是否营销订单';
COMMENT ON COLUMN slord.dwb_order_center_i.total_discount_amount IS '总优惠金额';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_id IS '退款ID';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_no IS '退款单号';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_type_name IS '退款类型';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_reason IS '退款原因';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_amount IS '退款金额';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_status_name IS '退款状态';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_apply_time IS '退款申请时间';
COMMENT ON COLUMN slord.dwb_order_center_i.refund_complete_time IS '退款完成时间';
COMMENT ON COLUMN slord.dwb_order_center_i.is_refund_order IS '是否退款订单';
COMMENT ON COLUMN slord.dwb_order_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slord.dwb_order_center_i.crt_cycle_id IS '创建批次';
COMMENT ON COLUMN slord.dwb_order_center_i.last_upd_cycle_id IS '更新批次';
COMMENT ON COLUMN slord.dwb_order_center_i.dw_last_update_date IS '更新时间';
