/* =====================================================
   表名: slord.dwb_user_behavior_tmp1
   规则: R0001 - 电商交易场景加工
   分布键: behavior_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 从订单主表 ods_order_main_f 出发, LEFT JOIN 商品维度 dim_product_d 取商品属性, 加工电商交易场景的行为明细(订单+商品共50字段), 产出到场景中间表 tmp1 供 F 表 UNION 合并
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_user_behavior_tmp1 (
    order_order_id          bigint,  /* 订单ID */
    order_order_no          varchar(50),  /* 订单编号 */
    order_order_status      varchar(20),  /* 订单状态 */
    order_order_status_name varchar(50),  /* 订单状态名称 */
    order_order_amount      decimal(18,2),  /* 订单金额 */
    order_discount_amount   decimal(18,2),  /* 优惠金额 */
    order_actual_amount     decimal(18,2),  /* 实付金额 */
    order_payment_method    varchar(50),  /* 支付方式 */
    order_payment_time      timestamp,  /* 支付时间 */
    order_shipping_fee      decimal(18,2),  /* 运费 */
    order_product_count     int,  /* 商品数量 */
    order_sku_count         int,  /* SKU数量 */
    order_is_first_order    int,  /* 是否首单 */
    order_coupon_id         int,  /* 优惠券ID */
    order_coupon_name       varchar(100),  /* 优惠券名称 */
    order_points_used       int,  /* 使用积分 */
    order_points_earned     int,  /* 获得积分 */
    order_complete_time     timestamp,  /* 完成时间 */
    order_cancel_time       timestamp,  /* 取消时间 */
    order_cancel_reason     varchar(200),  /* 取消原因 */
    order_merchant_id       int,  /* 商家ID */
    order_merchant_name     varchar(200),  /* 商家名称 */
    order_delivery_type     varchar(50),  /* 配送方式 */
    order_delivery_time     timestamp,  /* 配送时间 */
    order_receive_time      timestamp,  /* 收货时间 */
    order_receive_status    varchar(20),  /* 收货状态 */
    order_order_source      varchar(50),  /* 订单来源 */
    order_remark            varchar(500),  /* 订单备注 */
    order_invoice_type      varchar(20),  /* 发票类型 */
    order_invoice_title     varchar(200),  /* 发票抬头 */
    prod_product_id         bigint,  /* 商品ID */
    prod_product_name       varchar(200),  /* 商品名称 */
    prod_product_code       varchar(50),  /* 商品编码 */
    prod_sku_id             bigint,  /* SKU_ID */
    prod_sku_name           varchar(200),  /* SKU名称 */
    prod_brand_id           int,  /* 品牌ID */
    prod_brand_name         varchar(100),  /* 品牌名称 */
    prod_category_id        int,  /* 类目ID */
    prod_category_name      varchar(100),  /* 类目名称 */
    prod_category_level1    varchar(100),  /* 一级类目 */
    prod_category_level2    varchar(100),  /* 二级类目 */
    prod_category_level3    varchar(100),  /* 三级类目 */
    prod_price              decimal(18,2),  /* 商品价格 */
    prod_cost_price         decimal(18,2),  /* 成本价 */
    prod_profit_rate        decimal(5,2),  /* 利润率 */
    prod_stock_status       varchar(20),  /* 库存状态 */
    prod_sale_status        varchar(20),  /* 销售状态 */
    prod_product_type       varchar(50),  /* 商品类型 */
    prod_is_virtual         int,  /* 是否虚拟商品 */
    prod_supplier_id        int,  /* 供应商ID */
    /* 审计字段 */
    del_flag                NVARCHAR(1),
    crt_cycle_id            BIGINT,
    last_upd_cycle_id       BIGINT,
    dw_last_update_date     TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(behavior_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_user_behavior_tmp1 IS '用户行为宽表';

COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_id IS '订单ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_no IS '订单编号';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_status IS '订单状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_status_name IS '订单状态名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_amount IS '订单金额';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_discount_amount IS '优惠金额';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_actual_amount IS '实付金额';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_payment_method IS '支付方式';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_payment_time IS '支付时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_shipping_fee IS '运费';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_product_count IS '商品数量';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_sku_count IS 'SKU数量';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_is_first_order IS '是否首单';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_coupon_id IS '优惠券ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_coupon_name IS '优惠券名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_points_used IS '使用积分';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_points_earned IS '获得积分';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_complete_time IS '完成时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_cancel_time IS '取消时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_cancel_reason IS '取消原因';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_merchant_id IS '商家ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_merchant_name IS '商家名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_delivery_type IS '配送方式';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_delivery_time IS '配送时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_receive_time IS '收货时间';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_receive_status IS '收货状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_order_source IS '订单来源';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_remark IS '订单备注';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_invoice_type IS '发票类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.order_invoice_title IS '发票抬头';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_product_id IS '商品ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_product_name IS '商品名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_product_code IS '商品编码';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_sku_id IS 'SKU_ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_sku_name IS 'SKU名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_brand_id IS '品牌ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_brand_name IS '品牌名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_category_id IS '类目ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_category_name IS '类目名称';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_category_level1 IS '一级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_category_level2 IS '二级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_category_level3 IS '三级类目';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_price IS '商品价格';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_cost_price IS '成本价';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_profit_rate IS '利润率';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_stock_status IS '库存状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_sale_status IS '销售状态';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_product_type IS '商品类型';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_is_virtual IS '是否虚拟商品';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.prod_supplier_id IS '供应商ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_user_behavior_tmp1.dw_last_update_date IS '数仓最后更新时间';
