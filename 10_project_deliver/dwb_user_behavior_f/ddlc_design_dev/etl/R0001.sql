/* =====================================================
   ETL 转换脚本
   步骤: 1 (exec_sequence=1)
   目标表: slord.dwb_user_behavior_tmp1
   来源表:
     - ods.ods_order_main_f oom (主表)
     - dim.dim_product_d dpd (商品维度, LEFT JOIN)
   规则: R0001 电商交易场景加工
   说明: 从订单主表 ods_order_main_f 出发, LEFT JOIN 商品维度 dim_product_d 取商品属性,
         加工电商交易场景的行为明细(订单+商品共50字段), 产出到场景中间表 tmp1 供 F 表 UNION 合并。
         粒度无变化(一行=一个订单行为), 无 GROUP BY。
         注: 用户维度 dim_user_base_d (dub) 不在本场景 JOIN —— 其字段归 F 表合并规则,
             按编码规范 §3.9 禁止无效 JOIN, 不关联未被 SELECT 引用的表。
   ===================================================== */
SELECT
    COALESCE(oom.order_id, 0) AS order_order_id,
    COALESCE(oom.order_no, '') AS order_order_no,
    COALESCE(oom.order_status, '') AS order_order_status,
    CASE oom.order_status
        WHEN 'PENDING'   THEN '待支付'
        WHEN 'PAID'      THEN '已支付'
        WHEN 'SHIPPED'   THEN '已发货'
        WHEN 'COMPLETED' THEN '已完成'
        WHEN 'CANCELLED' THEN '已取消'
        ELSE '未知'
    END AS order_order_status_name,
    COALESCE(oom.order_amount, 0) AS order_order_amount,
    COALESCE(oom.discount_amount, 0) AS order_discount_amount,
    COALESCE(oom.actual_amount, 0) AS order_actual_amount,
    COALESCE(oom.payment_method, '') AS order_payment_method,
    oom.payment_time AS order_payment_time,
    COALESCE(oom.shipping_fee, 0) AS order_shipping_fee,
    COALESCE(oom.product_count, 0) AS order_product_count,
    COALESCE(oom.sku_count, 0) AS order_sku_count,
    COALESCE(oom.is_first_order, 0) AS order_is_first_order,
    COALESCE(oom.coupon_id, 0) AS order_coupon_id,
    COALESCE(oom.coupon_name, '') AS order_coupon_name,
    COALESCE(oom.points_used, 0) AS order_points_used,
    COALESCE(oom.points_earned, 0) AS order_points_earned,
    oom.complete_time AS order_complete_time,
    oom.cancel_time AS order_cancel_time,
    COALESCE(oom.cancel_reason, '') AS order_cancel_reason,
    COALESCE(oom.merchant_id, 0) AS order_merchant_id,
    COALESCE(oom.merchant_name, '') AS order_merchant_name,
    COALESCE(oom.delivery_type, '') AS order_delivery_type,
    oom.delivery_time AS order_delivery_time,
    oom.receive_time AS order_receive_time,
    COALESCE(oom.receive_status, '') AS order_receive_status,
    COALESCE(oom.order_source, '') AS order_order_source,
    COALESCE(oom.remark, '') AS order_remark,
    COALESCE(oom.invoice_type, '') AS order_invoice_type,
    COALESCE(oom.invoice_title, '') AS order_invoice_title,
    COALESCE(dpd.product_id, 0) AS prod_product_id,
    COALESCE(dpd.product_name, '') AS prod_product_name,
    COALESCE(dpd.product_code, '') AS prod_product_code,
    COALESCE(dpd.sku_id, 0) AS prod_sku_id,
    COALESCE(dpd.sku_name, '') AS prod_sku_name,
    COALESCE(dpd.brand_id, 0) AS prod_brand_id,
    COALESCE(dpd.brand_name, '') AS prod_brand_name,
    COALESCE(dpd.category_id, 0) AS prod_category_id,
    COALESCE(dpd.category_name, '') AS prod_category_name,
    COALESCE(dpd.category_level1, '') AS prod_category_level1,
    COALESCE(dpd.category_level2, '') AS prod_category_level2,
    COALESCE(dpd.category_level3, '') AS prod_category_level3,
    COALESCE(dpd.price, 0) AS prod_price,
    COALESCE(dpd.cost_price, 0) AS prod_cost_price,
    CASE
        WHEN dpd.price IS NOT NULL AND dpd.price > 0
            THEN ROUND((dpd.price - COALESCE(dpd.cost_price, 0)) / dpd.price * 100, 2)
        ELSE 0
    END AS prod_profit_rate,
    COALESCE(dpd.stock_status, '') AS prod_stock_status,
    COALESCE(dpd.sale_status, '') AS prod_sale_status,
    COALESCE(dpd.product_type, '') AS prod_product_type,
    COALESCE(dpd.is_virtual, 0) AS prod_is_virtual,
    COALESCE(dpd.supplier_id, 0) AS prod_supplier_id,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM ods.ods_order_main_f oom
LEFT JOIN dim.dim_product_d dpd
    ON oom.product_id = dpd.product_id
    AND dpd.del_flag = 'N'
WHERE oom.del_flag = 'N';
