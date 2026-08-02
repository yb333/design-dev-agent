/* =====================================================
   表名: slshp.dwb_shop_center_f
   规则: R0001 - 店铺中心宽表加工
   分布键: shop_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 以 dim_shop_f 为主表（已是店铺粒度），LEFT JOIN dim_region_f 取省份名称； 订单明细 (dwd_order_f) 与评价明细 (dwd_review_f) 因粒度细于店铺，先经 CTE 按 shop_id 聚合收敛到店铺粒度后再 LEFT JOIN 回主表，一次性产出店铺级宽表。 采用 CTE 内联而非物理中间表，因聚合结果只在本规则内使用一次、无独立校验诉求。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slshp.dwb_shop_center_f (
    shop_id             bigint,  /* 店铺ID */
    shop_name           varchar(200),  /* 店铺名称 */
    company_name        varchar(200),  /* 公司名称 */
    open_time           datetime,  /* 开店时间 */
    province_code       varchar(20),  /* 省份编码 */
    shop_score          decimal(3,2),  /* 店铺评分 */
    service_score       decimal(3,2),  /* 服务评分 */
    logistics_score     decimal(3,2),  /* 物流评分 */
    shop_type_name      varchar(50),  /* 店铺类型 */
    shop_status_name    varchar(50),  /* 店铺状态 */
    open_days           int,  /* 营业天数 */
    province_name       varchar(50),  /* 省份名称 */
    total_order_cnt     int,  /* 累计订单数 */
    total_sales_amount  decimal(18,2),  /* 累计销售额 */
    total_buyer_cnt     int,  /* 累计购买人数 */
    review_cnt          int,  /* 评价数 */
    del_flag            NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id        BIGINT,  /* 创建批次ID */
    last_upd_cycle_id   BIGINT,  /* 最后更新批次ID */
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE,  /* 数仓最后更新时间 */
    /* 审计字段 */
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
COMMENT ON COLUMN slshp.dwb_shop_center_f.company_name IS '公司名称';
COMMENT ON COLUMN slshp.dwb_shop_center_f.open_time IS '开店时间';
COMMENT ON COLUMN slshp.dwb_shop_center_f.province_code IS '省份编码';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_score IS '店铺评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.service_score IS '服务评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.logistics_score IS '物流评分';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_type_name IS '店铺类型';
COMMENT ON COLUMN slshp.dwb_shop_center_f.shop_status_name IS '店铺状态';
COMMENT ON COLUMN slshp.dwb_shop_center_f.open_days IS '营业天数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.province_name IS '省份名称';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_order_cnt IS '累计订单数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_sales_amount IS '累计销售额';
COMMENT ON COLUMN slshp.dwb_shop_center_f.total_buyer_cnt IS '累计购买人数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.review_cnt IS '评价数';
COMMENT ON COLUMN slshp.dwb_shop_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slshp.dwb_shop_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.dw_last_update_date IS '数仓最后更新时间';
COMMENT ON COLUMN slshp.dwb_shop_center_f.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slshp.dwb_shop_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slshp.dwb_shop_center_f.dw_last_update_date IS '数仓最后更新时间';
