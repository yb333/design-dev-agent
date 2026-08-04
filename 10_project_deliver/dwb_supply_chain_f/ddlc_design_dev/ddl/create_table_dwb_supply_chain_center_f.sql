/* =====================================================
   表名: slscc.dwb_supply_chain_center_f
   规则: R0001 - 供应链中心宽表写入
   分布键: purchase_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-04
   说明: 以采购事实表(dp)为主表锚定粒度，LEFT JOIN 供应商/商品/仓库维度表补充属性，LEFT JOIN 库存事实表取当前库存与锁定库存，通过CTE预聚合销售表按product_id统计近30天销量后关联，计算库存周转天数，写入供应链中心宽表
   ===================================================== */

CREATE TABLE IF NOT EXISTS slscc.dwb_supply_chain_center_f (
    purchase_id          bigint,
    purchase_no          varchar(64),
    purchase_status_name varchar(50),
    create_time          datetime,
    supplier_id          bigint,
    product_id           bigint,
    purchase_qty         int,
    purchase_price       decimal(18,2),
    purchase_amount      decimal(18,2),
    warehouse_id         bigint,
    supplier_name        varchar(200),
    supplier_level_name  varchar(50),
    cooperation_years    int,
    product_name         varchar(200),
    warehouse_name       varchar(100),
    warehouse_type_name  varchar(50),
    current_stock_qty    int,
    locked_qty           int,
    stock_days           int,
    del_flag             NVARCHAR(1),
    crt_cycle_id         BIGINT,
    last_upd_cycle_id    BIGINT,
    dw_last_update_date  TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(purchase_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slscc.dwb_supply_chain_center_f IS '供应链中心宽表';

COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_id IS '采购单ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_no IS '采购单号';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_status_name IS '采购状态';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.create_time IS '创建时间';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.supplier_id IS '供应商ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.product_id IS '商品ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_qty IS '采购数量';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_price IS '采购单价';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_amount IS '采购金额';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_id IS '仓库ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.supplier_name IS '供应商名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.supplier_level_name IS '供应商等级';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.cooperation_years IS '合作年限';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.product_name IS '商品名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_name IS '仓库名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_type_name IS '仓库类型';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.current_stock_qty IS '当前库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.locked_qty IS '锁定库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.stock_days IS '库存周转天数';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.dw_last_update_date IS '数仓最后更新时间';
