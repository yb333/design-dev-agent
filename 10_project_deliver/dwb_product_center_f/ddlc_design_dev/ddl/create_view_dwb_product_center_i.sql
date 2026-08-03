/* I视图: slprd.dwb_product_center_i（商品中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slprd.dwb_product_center_i AS
SELECT
    product_id,
    product_name,
    product_code,
    product_status_name,
    create_time,
    on_shelf_time,
    cost_price,
    sale_price,
    market_price,
    discount_rate,
    gross_profit,
    gross_profit_rate,
    category_id,
    category_name,
    category_path,
    brand_id,
    brand_name,
    brand_origin,
    shop_id,
    shop_name,
    stock_qty,
    locked_qty,
    available_qty,
    warning_qty,
    stock_status,
    weight,
    volume,
    product_tag,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slprd.dwb_product_center_f;

COMMENT ON TABLE slprd.dwb_product_center_i IS '商品中心宽表（视图）';

COMMENT ON COLUMN slprd.dwb_product_center_i.product_id IS '商品ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.product_name IS '商品名称';
COMMENT ON COLUMN slprd.dwb_product_center_i.product_code IS '商品编码';
COMMENT ON COLUMN slprd.dwb_product_center_i.product_status_name IS '商品状态';
COMMENT ON COLUMN slprd.dwb_product_center_i.create_time IS '创建时间';
COMMENT ON COLUMN slprd.dwb_product_center_i.on_shelf_time IS '上架时间';
COMMENT ON COLUMN slprd.dwb_product_center_i.cost_price IS '成本价';
COMMENT ON COLUMN slprd.dwb_product_center_i.sale_price IS '销售价';
COMMENT ON COLUMN slprd.dwb_product_center_i.market_price IS '市场价';
COMMENT ON COLUMN slprd.dwb_product_center_i.discount_rate IS '折扣率(%)';
COMMENT ON COLUMN slprd.dwb_product_center_i.gross_profit IS '单品毛利';
COMMENT ON COLUMN slprd.dwb_product_center_i.gross_profit_rate IS '毛利率(%)';
COMMENT ON COLUMN slprd.dwb_product_center_i.category_id IS '分类ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.category_name IS '分类名称';
COMMENT ON COLUMN slprd.dwb_product_center_i.category_path IS '分类路径';
COMMENT ON COLUMN slprd.dwb_product_center_i.brand_id IS '品牌ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.brand_name IS '品牌名称';
COMMENT ON COLUMN slprd.dwb_product_center_i.brand_origin IS '品牌产地';
COMMENT ON COLUMN slprd.dwb_product_center_i.shop_id IS '店铺ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.shop_name IS '店铺名称';
COMMENT ON COLUMN slprd.dwb_product_center_i.stock_qty IS '库存数量';
COMMENT ON COLUMN slprd.dwb_product_center_i.locked_qty IS '锁定数量';
COMMENT ON COLUMN slprd.dwb_product_center_i.available_qty IS '可售数量';
COMMENT ON COLUMN slprd.dwb_product_center_i.warning_qty IS '库存预警值';
COMMENT ON COLUMN slprd.dwb_product_center_i.stock_status IS '库存状态';
COMMENT ON COLUMN slprd.dwb_product_center_i.weight IS '重量(kg)';
COMMENT ON COLUMN slprd.dwb_product_center_i.volume IS '体积(m³)';
COMMENT ON COLUMN slprd.dwb_product_center_i.product_tag IS '商品标签';
COMMENT ON COLUMN slprd.dwb_product_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slprd.dwb_product_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_i.dw_last_update_date IS '数仓最后更新时间';
