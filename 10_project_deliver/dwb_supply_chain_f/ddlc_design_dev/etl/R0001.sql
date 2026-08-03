/* R0001: 供应链中心宽表全量加工
   设计意图：以采购事实表(dpf)为主表，左联供应商/商品/仓库维度表与库存/销售事实表，
   单条 SELECT 一次性产出宽表；销售表(dsales)经 CTE 按 product_id 聚合收敛后再 JOIN，
   保障产出粒度=采购单。 */
WITH
/* CTE sales_agg: 把销售事实表(dsales)按 product_id 聚合统计近30天销量(sales_qty_30d)，
   聚合后 product_id 唯一，供主查询安全 LEFT JOIN 计算 stock_days（避免采购单因商品多次销售而发散）。 */
sales_agg AS (
    SELECT
        product_id,
        COALESCE(SUM(sales_qty_30d), 0) AS sales_qty_30d
    FROM slscc.dwd_sales_f
    WHERE del_flag = 'N'
    GROUP BY product_id
)

SELECT
    dpf.purchase_id AS purchase_id,
    dpf.purchase_no AS purchase_no,
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
    COALESCE(dpf.purchase_qty, 0) AS purchase_qty,
    COALESCE(dpf.purchase_price, 0) AS purchase_price,
    dpf.warehouse_id AS warehouse_id,
    COALESCE(dsf.supplier_name, '') AS supplier_name,
    CASE dsf.supplier_level
        WHEN 'A' THEN 'A级供应商'
        WHEN 'B' THEN 'B级供应商'
        WHEN 'C' THEN 'C级供应商'
        ELSE '其他'
    END AS supplier_level_name,
    COALESCE(dsf.cooperation_years, 0) AS cooperation_years,
    COALESCE(dpf2.product_name, '') AS product_name,
    COALESCE(dwf.warehouse_name, '') AS warehouse_name,
    CASE dwf.warehouse_type
        WHEN 'SELF' THEN '自营仓'
        WHEN 'THIRD_PARTY' THEN '第三方仓'
        ELSE '其他'
    END AS warehouse_type_name,
    COALESCE(dif.stock_qty, 0) AS current_stock_qty,
    COALESCE(dif.locked_qty, 0) AS locked_qty,
    COALESCE(dpf.purchase_qty, 0) * COALESCE(dpf.purchase_price, 0) AS purchase_amount,
    (dif.stock_qty - dif.locked_qty) / NULLIF(sales_agg.sales_qty_30d, 0) AS stock_days,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM slscc.dwd_purchase_f dpf
LEFT JOIN slscc.dim_supplier_f dsf
    ON dpf.supplier_id = dsf.supplier_id
    AND dsf.del_flag = 'N'
LEFT JOIN slscc.dim_product_f dpf2
    ON dpf.product_id = dpf2.product_id
    AND dpf2.del_flag = 'N'
LEFT JOIN slscc.dim_warehouse_f dwf
    ON dpf.warehouse_id = dwf.warehouse_id
    AND dwf.del_flag = 'N'
LEFT JOIN slscc.dwd_inventory_f dif
    ON dpf.product_id = dif.product_id
    AND dpf.warehouse_id = dif.warehouse_id
    AND dif.del_flag = 'N'
LEFT JOIN sales_agg
    ON dpf.product_id = sales_agg.product_id
WHERE dpf.del_flag = 'N';
