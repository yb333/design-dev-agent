/* =====================================================
   表名: slshp.dwb_shop_center_f
   规则: R0001 - 店铺中心宽表组装
   分布键: shop_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 以店铺维度表为主表，LEFT JOIN 地区维度表获取省份名称； 通过 CTE 预聚合订单/评价事实表到店铺粒度，避免多表直接 JOIN 的 fan-out； 标量加工字段（类型/状态映射、营业天数）在主表行内计算。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slshp.dwb_shop_center_f (
    shop_id             bigint,
    shop_name           varchar(200),
    shop_type_name      varchar(50),
    shop_status_name    varchar(50),
    company_name        varchar(200),
    open_time           datetime,
    open_days           int,
    province_code       varchar(20),
    province_name       varchar(50),
    shop_score          decimal(3,2),
    service_score       decimal(3,2),
    logistics_score     decimal(3,2),
    total_order_cnt     int,
    total_sales_amount  decimal(18,2),
    total_buyer_cnt     int,
    review_cnt          int,
    del_flag            NVARCHAR(1),
    crt_cycle_id        BIGINT,
    last_upd_cycle_id   BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(shop_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slshp.dwb_shop_center_f IS '店铺中心宽表';

COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_id IS '店铺ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_name IS '店铺名称';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_type_name IS '店铺类型';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_status_name IS '店铺状态';
COMMENT ON COLUMN slshp.dwb_shop_center_f.company_name IS '公司名称';
COMMENT ON COLUMN slshp.dwb_shop_center_f.open_time IS '开店时间';
COMMENT ON COLUMN slshp.dwb_shop_center_f.open_days IS '营业天数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.province_code IS '省份编码';
COMMENT ON COLUMN slshp.dwb_shop_center_f.province_name IS '省份名称';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_score IS '店铺评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.service_score IS '服务评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.logistics_score IS '物流评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_order_cnt IS '累计订单数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_sales_amount IS '累计销售额';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_buyer_cnt IS '累计购买人数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.review_cnt IS '评价数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slshp.dwb_shop_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.dw_last_update_date IS '数仓最后更新时间';
