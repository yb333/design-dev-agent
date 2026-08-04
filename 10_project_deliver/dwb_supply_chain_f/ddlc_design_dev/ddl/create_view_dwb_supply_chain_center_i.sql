/* I视图: slscc.dwb_supply_chain_center_i（供应链中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slscc.dwb_supply_chain_center_i AS
SELECT
    purchase_id,
    purchase_no,
    purchase_status_name,
    create_time,
    supplier_id,
    product_id,
    purchase_qty,
    purchase_price,
    purchase_amount,
    warehouse_id,
    supplier_name,
    supplier_level_name,
    cooperation_years,
    product_name,
    warehouse_name,
    warehouse_type_name,
    current_stock_qty,
    locked_qty,
    stock_days,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM slscc.dwb_supply_chain_center_f;

COMMENT ON TABLE slscc.dwb_supply_chain_center_i IS '供应链中心宽表（视图）';

COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_id IS '采购单ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_no IS '采购单号';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_status_name IS '采购状态';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.create_time IS '创建时间';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.supplier_id IS '供应商ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.product_id IS '商品ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_qty IS '采购数量';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_price IS '采购单价';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.purchase_amount IS '采购金额';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.warehouse_id IS '仓库ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.supplier_name IS '供应商名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.supplier_level_name IS '供应商等级';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.cooperation_years IS '合作年限';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.product_name IS '商品名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.warehouse_name IS '仓库名称';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.warehouse_type_name IS '仓库类型';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.current_stock_qty IS '当前库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.locked_qty IS '锁定库存';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.stock_days IS '库存周转天数';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.del_flag IS '删除标识';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slscc.dwb_supply_chain_center_i.dw_last_update_date IS '数仓最后更新时间';
