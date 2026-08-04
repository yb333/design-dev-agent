/* =====================================================
   R0001: 供应链中心宽表写入
   目标表: slscc.dwb_supply_chain_center_f
   设计意图: 以采购事实表(dpf)为主表锚定粒度，LEFT JOIN 供应商/商品/仓库
             维度表补充属性，LEFT JOIN 库存事实表取当前库存与锁定库存，
             通过CTE预聚合销售表按product_id统计近30天销量后关联，
             计算库存周转天数，写入供应链中心宽表
   ===================================================== */

/* CTE: 销售事实表按product_id预聚合近30天销量，收敛到商品粒度避免JOIN发散 */
WITH sales_agg AS (
    SELECT
        dsales.product_id AS product_id,
        COALESCE(SUM(dsales.sales_qty_30d), 0) AS sales_qty_30d_sum
    FROM sdinv.dwd_sales_f dsales
    WHERE dsales.del_flag = 'N'
    GROUP BY dsales.product_id
)

SELECT
    dpf.purchase_id AS purchase_id,
    dpf.purchase_no AS purchase_no,
    /* 采购状态码转中文映射 */
    CASE dpf.purchase_status
        WHEN 'DRAFT' THEN '草稿'
        WHEN 'SUBMITTED' THEN '已提交'
        WHEN 'APPROVED' THEN '已审批'
        WHEN 'RECEIVED' THEN '已入库'
        WHEN 'CLOSED' THEN '已关闭'
        ELSE '其他'
    END AS purchase_status_name,
    dpf.create_time AS create_time,
    dpf.supplier_id AS supplier_id,
    dpf.product_id AS product_id,
    dpf.purchase_qty AS purchase_qty,
    dpf.purchase_price AS purchase_price,
    /* 采购金额 = 采购数量 × 采购单价 */
    COALESCE(dpf.purchase_qty, 0) * COALESCE(dpf.purchase_price, 0) AS purchase_amount,
    dpf.warehouse_id AS warehouse_id,
    COALESCE(dsf.supplier_name, '') AS supplier_name,
    /* 供应商等级码转中文映射 */
    CASE dsf.supplier_level
        WHEN 'A' THEN 'A级供应商'
        WHEN 'B' THEN 'B级供应商'
        WHEN 'C' THEN 'C级供应商'
        ELSE '其他'
    END AS supplier_level_name,
    COALESCE(dsf.cooperation_years, 0) AS cooperation_years,
    COALESCE(dpf2.product_name, '') AS product_name,
    COALESCE(dwf.warehouse_name, '') AS warehouse_name,
    /* 仓库类型码转中文映射 */
    CASE dwf.warehouse_type
        WHEN 'SELF' THEN '自营仓'
        WHEN 'THIRD_PARTY' THEN '第三方仓'
        ELSE '其他'
    END AS warehouse_type_name,
    COALESCE(dif.stock_qty, 0) AS current_stock_qty,
    COALESCE(dif.locked_qty, 0) AS locked_qty,
    /* 库存周转天数 = (当前库存 - 锁定库存) / 近30天销量，除零保护用NULLIF */
    (COALESCE(dif.stock_qty, 0) - COALESCE(dif.locked_qty, 0))
        / NULLIF(sales_agg.sales_qty_30d_sum, 0) AS stock_days,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdinv.dwd_purchase_f dpf
LEFT JOIN dim.dim_supplier_f dsf
    ON dpf.supplier_id = dsf.supplier_id
    AND dsf.del_flag = 'N'
LEFT JOIN dim.dim_product_f dpf2
    ON dpf.product_id = dpf2.product_id
    AND dpf2.del_flag = 'N'
LEFT JOIN dim.dim_warehouse_f dwf
    ON dpf.warehouse_id = dwf.warehouse_id
    AND dwf.del_flag = 'N'
LEFT JOIN sdinv.dwd_inventory_f dif
    ON dpf.product_id = dif.product_id
    AND dpf.warehouse_id = dif.warehouse_id
    AND dif.del_flag = 'N'
LEFT JOIN sales_agg
    ON dpf.product_id = sales_agg.product_id
WHERE dpf.del_flag = 'N';
