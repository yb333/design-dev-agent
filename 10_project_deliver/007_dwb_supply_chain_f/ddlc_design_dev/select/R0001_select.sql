/* =====================================================
   R0001: 供应链中心宽表主加工
   目标表: slscc.dwb_supply_chain_center_f
   设计意图: 以采购事实表为主表，左关联供应商/商品/仓库维度及库存事实表，
             加工状态/等级/类型映射与金额/周转天数，产出供应链中心宽表 F 表
   粒度: 一行 = 一条供应链中心记录 (按 purchase_id)
   加载策略: 全量调度
   来源表:
     - sdinv.dwd_purchase_f (dpf, 主表)
     - dim.dim_supplier_f (dsf)
     - dim.dim_product_f (dpf4)
     - dim.dim_warehouse_f (dwf)
     - sdinv.dwd_inventory_f (dif, 需收敛)
   ===================================================== */

SELECT
    dpf.purchase_id AS purchase_id,
    dpf.purchase_no AS purchase_no,
    /* 采购状态码转中文 (源字段 dpf.purchase_status) */
    CASE dpf.purchase_status
        WHEN 'DRAFT'     THEN '草稿'
        WHEN 'SUBMITTED' THEN '已提交'
        WHEN 'APPROVED'  THEN '已审批'
        WHEN 'RECEIVED'  THEN '已入库'
        WHEN 'CLOSED'    THEN '已关闭'
        ELSE '其他'
    END AS purchase_status_name,
    dpf.create_time AS create_time,
    dpf.supplier_id AS supplier_id,
    COALESCE(dsf.supplier_name, '') AS supplier_name,
    /* 供应商等级码转中文 (源字段 dsf.supplier_level) */
    CASE dsf.supplier_level
        WHEN 'A' THEN 'A级供应商'
        WHEN 'B' THEN 'B级供应商'
        WHEN 'C' THEN 'C级供应商'
        ELSE '其他'
    END AS supplier_level_name,
    COALESCE(dsf.cooperation_years, 0) AS cooperation_years,
    dpf.product_id AS product_id,
    COALESCE(dpf4.product_name, '') AS product_name,
    COALESCE(dpf.purchase_qty, 0) AS purchase_qty,
    COALESCE(dpf.purchase_price, 0) AS purchase_price,
    /* 采购金额 = 采购数量 × 采购单价 */
    COALESCE(dpf.purchase_qty, 0) * COALESCE(dpf.purchase_price, 0) AS purchase_amount,
    dpf.warehouse_id AS warehouse_id,
    COALESCE(dwf.warehouse_name, '') AS warehouse_name,
    /* 仓库类型码转中文 (源字段 dwf.warehouse_type) */
    CASE dwf.warehouse_type
        WHEN 'SELF'         THEN '自营仓'
        WHEN 'THIRD_PARTY'  THEN '第三方仓'
        ELSE '其他'
    END AS warehouse_type_name,
    COALESCE(inv.stock_qty, 0) AS current_stock_qty,
    COALESCE(inv.locked_qty, 0) AS locked_qty,
    /* ⚠️ 上游缺口: 库存周转天数依赖销量源表 (近30天销量),
       该源表不在 source_tables 中 (见 ts.json design_logic 待补源说明),
       暂输出 NULL, 待销量事实表接入后补全计算逻辑 */
    NULL::int AS stock_days,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdinv.dwd_purchase_f dpf
LEFT JOIN dim.dim_supplier_f dsf
    ON dpf.supplier_id = dsf.supplier_id
    AND dsf.del_flag = 'N'
LEFT JOIN dim.dim_product_f dpf4
    ON dpf.product_id = dpf4.product_id
    AND dpf4.del_flag = 'N'
LEFT JOIN dim.dim_warehouse_f dwf
    ON dpf.warehouse_id = dwf.warehouse_id
    AND dwf.del_flag = 'N'
/* 库存收敛 (关联安全策略): dwd_inventory_f 按 (product_id, warehouse_id) 可能有多行,
   取每个组合的最新有效库存行 (_rn=1), 避免 LEFT JOIN 导致主表放大.
   实现 join_safety strategy: GROUP BY (product_id, warehouse_id) 收敛 + 取当前有效库存行 */
LEFT JOIN (
    SELECT
        product_id,
        warehouse_id,
        stock_qty,
        locked_qty,
        ROW_NUMBER() OVER (
            PARTITION BY product_id, warehouse_id
            ORDER BY update_time DESC NULLS LAST
        ) AS _rn
    FROM sdinv.dwd_inventory_f
    WHERE del_flag = 'N'
) inv
    ON dpf.product_id = inv.product_id
    AND dpf.warehouse_id = inv.warehouse_id
    AND inv._rn = 1
WHERE dpf.del_flag = 'N';
