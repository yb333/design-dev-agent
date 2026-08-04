/* I视图: slshp.dwb_shop_center_i（店铺中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slshp.dwb_shop_center_i AS
SELECT
    shop_id,
    shop_name,
    shop_type_name,
    shop_status_name,
    company_name,
    open_time,
    open_days,
    province_code,
    province_name,
    shop_score,
    service_score,
    logistics_score,
    total_order_cnt,
    total_sales_amount,
    total_buyer_cnt,
    review_cnt,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slshp.dwb_shop_center_f;

COMMENT ON TABLE slshp.dwb_shop_center_i IS '店铺中心宽表（视图）';

COMMENT ON COLUMN slshp.dwb_shop_center_i.shop_id IS '店铺ID';
COMMENT ON COLUMN slshp.dwb_shop_center_i.shop_name IS '店铺名称';
COMMENT ON COLUMN slshp.dwb_shop_center_i.shop_type_name IS '店铺类型';
COMMENT ON COLUMN slshp.dwb_shop_center_i.shop_status_name IS '店铺状态';
COMMENT ON COLUMN slshp.dwb_shop_center_i.company_name IS '公司名称';
COMMENT ON COLUMN slshp.dwb_shop_center_i.open_time IS '开店时间';
COMMENT ON COLUMN slshp.dwb_shop_center_i.open_days IS '营业天数';
COMMENT ON COLUMN slshp.dwb_shop_center_i.province_code IS '省份编码';
COMMENT ON COLUMN slshp.dwb_shop_center_i.province_name IS '省份名称';
COMMENT ON COLUMN slshp.dwb_shop_center_i.shop_score IS '店铺评分';
COMMENT ON COLUMN slshp.dwb_shop_center_i.service_score IS '服务评分';
COMMENT ON COLUMN slshp.dwb_shop_center_i.logistics_score IS '物流评分';
COMMENT ON COLUMN slshp.dwb_shop_center_i.total_order_cnt IS '累计订单数';
COMMENT ON COLUMN slshp.dwb_shop_center_i.total_sales_amount IS '累计销售额';
COMMENT ON COLUMN slshp.dwb_shop_center_i.total_buyer_cnt IS '累计购买人数';
COMMENT ON COLUMN slshp.dwb_shop_center_i.review_cnt IS '评价数';
COMMENT ON COLUMN slshp.dwb_shop_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slshp.dwb_shop_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_i.dw_last_update_date IS '数仓最后更新时间';
