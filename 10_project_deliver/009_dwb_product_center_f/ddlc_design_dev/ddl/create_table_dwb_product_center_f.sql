/* =====================================================
   表名: slprd.dwb_product_center_f
   规则: R0003 - 商品中心宽表装配
   分布键: product_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 以 dim_product_f 为主表，LEFT JOIN 分类/品牌/店铺维度、库存快照及销售/评价汇总中间表，装配出每行一个商品的宽表(含价格折扣、库存状态等加工字段)
   ===================================================== */

CREATE TABLE IF NOT EXISTS slprd.dwb_product_center_f (
    product_id          bigint,  /* 商品ID */
    product_name        varchar(200),  /* 商品名称 */
    product_code        varchar(50),  /* 商品编码 */
    create_time         datetime,  /* 创建时间 */
    on_shelf_time       datetime,  /* 上架时间 */
    cost_price          decimal(18,2),  /* 成本价 */
    sale_price          decimal(18,2),  /* 销售价 */
    market_price        decimal(18,2),  /* 市场价 */
    weight              decimal(10,2),  /* 重量(kg) */
    volume              decimal(10,4),  /* 体积(m³) */
    product_tag         varchar(200),  /* 商品标签 */
    category_id         bigint,  /* 分类ID */
    category_name       varchar(100),  /* 分类名称 */
    category_path       varchar(200),  /* 分类路径 */
    brand_id            bigint,  /* 品牌ID */
    brand_name          varchar(100),  /* 品牌名称 */
    brand_origin        varchar(50),  /* 品牌产地 */
    shop_id             bigint,  /* 店铺ID */
    shop_name           varchar(200),  /* 店铺名称 */
    stock_qty           int,  /* 库存数量 */
    locked_qty          int,  /* 锁定数量 */
    warning_qty         int,  /* 库存预警值 */
    product_status_name varchar(20),  /* 商品状态 */
    discount_rate       decimal(5,2),  /* 折扣率(%) */
    gross_profit        decimal(18,2),  /* 单品毛利 */
    gross_profit_rate   decimal(5,2),  /* 毛利率(%) */
    available_qty       int,  /* 可售数量 */
    stock_status        varchar(20),  /* 库存状态 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(product_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slprd.dwb_product_center_f IS '商品中心宽表';

COMMENT ON COLUMN slprd.dwb_product_center_f.product_id IS '商品ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.product_name IS '商品名称';
COMMENT ON COLUMN slprd.dwb_product_center_f.product_code IS '商品编码';
COMMENT ON COLUMN slprd.dwb_product_center_f.create_time IS '创建时间';
COMMENT ON COLUMN slprd.dwb_product_center_f.on_shelf_time IS '上架时间';
COMMENT ON COLUMN slprd.dwb_product_center_f.cost_price IS '成本价';
COMMENT ON COLUMN slprd.dwb_product_center_f.sale_price IS '销售价';
COMMENT ON COLUMN slprd.dwb_product_center_f.market_price IS '市场价';
COMMENT ON COLUMN slprd.dwb_product_center_f.weight IS '重量(kg)';
COMMENT ON COLUMN slprd.dwb_product_center_f.volume IS '体积(m³)';
COMMENT ON COLUMN slprd.dwb_product_center_f.product_tag IS '商品标签';
COMMENT ON COLUMN slprd.dwb_product_center_f.category_id IS '分类ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.category_name IS '分类名称';
COMMENT ON COLUMN slprd.dwb_product_center_f.category_path IS '分类路径';
COMMENT ON COLUMN slprd.dwb_product_center_f.brand_id IS '品牌ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.brand_name IS '品牌名称';
COMMENT ON COLUMN slprd.dwb_product_center_f.brand_origin IS '品牌产地';
COMMENT ON COLUMN slprd.dwb_product_center_f.shop_id IS '店铺ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.shop_name IS '店铺名称';
COMMENT ON COLUMN slprd.dwb_product_center_f.stock_qty IS '库存数量';
COMMENT ON COLUMN slprd.dwb_product_center_f.locked_qty IS '锁定数量';
COMMENT ON COLUMN slprd.dwb_product_center_f.warning_qty IS '库存预警值';
COMMENT ON COLUMN slprd.dwb_product_center_f.product_status_name IS '商品状态';
COMMENT ON COLUMN slprd.dwb_product_center_f.discount_rate IS '折扣率(%)';
COMMENT ON COLUMN slprd.dwb_product_center_f.gross_profit IS '单品毛利';
COMMENT ON COLUMN slprd.dwb_product_center_f.gross_profit_rate IS '毛利率(%)';
COMMENT ON COLUMN slprd.dwb_product_center_f.available_qty IS '可售数量';
COMMENT ON COLUMN slprd.dwb_product_center_f.stock_status IS '库存状态';
COMMENT ON COLUMN slprd.dwb_product_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slprd.dwb_product_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slprd.dwb_product_center_f.dw_last_update_date IS '数仓最后更新时间';
