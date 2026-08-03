/* =====================================================
   表名: slscc.dwb_supply_chain_center_f
   规则: R0001 - 供应链中心宽表全量加工
   分布键: purchase_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 以采购事实表(dpf)为主表，左联供应商/商品/仓库维度表与库存/销售事实表，单条 INSERT 一次性产出宽表；销售表(dsales)因 sales_product_id 多行会发散，必须经 CTE 按 product_id 聚合收敛后再 JOIN，保障产出粒度=采购单。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slscc.dwb_supply_chain_center_f (
    purchase_id          bigint,  /* 采购单ID */
    purchase_no          varchar(64),  /* 采购单号 */
    purchase_status_name varchar(50),  /* 采购状态 */
    create_time          datetime,  /* 创建时间 */
    supplier_id          bigint,  /* 供应商ID */
    product_id           bigint,  /* 商品ID */
    purchase_qty         int,  /* 采购数量 */
    purchase_price       decimal(18,2),  /* 采购单价 */
    warehouse_id         bigint,  /* 仓库ID */
    supplier_name        varchar(200),  /* 供应商名称 */
    supplier_level_name  varchar(50),  /* 供应商等级 */
    cooperation_years    int,  /* 合作年限 */
    product_name         varchar(200),  /* 商品名称 */
    warehouse_name       varchar(100),  /* 仓库名称 */
    warehouse_type_name  varchar(50),  /* 仓库类型 */
    current_stock_qty    int,  /* 当前库存 */
    locked_qty           int,  /* 锁定库存 */
    purchase_amount      decimal(18,2),  /* 采购金额 */
    stock_days           int,  /* 库存周转天数 */
    del_flag             NVARCHAR(1),  /* 删除标识 */
    crt_cycle_id         BIGINT,  /* 创建批次ID */
    last_upd_cycle_id    BIGINT,  /* 最后更新批次ID */
    dw_last_update_date  TIMESTAMP(0) WITHOUT TIME ZONE  /* 数仓最后更新时间 */
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
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_id IS '仓库ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.supplier_name IS '供应商名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.supplier_level_name IS '供应商等级';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.cooperation_years IS '合作年限';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.product_name IS '商品名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_name IS '仓库名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.warehouse_type_name IS '仓库类型';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.current_stock_qty IS '当前库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.locked_qty IS '锁定库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.purchase_amount IS '采购金额';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.stock_days IS '库存周转天数';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.del_flag IS '删除标识';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_f.dw_last_update_date IS '数仓最后更新时间';
