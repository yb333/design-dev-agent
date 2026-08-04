/* =====================================================
   ETL 转换脚本（SELECT 部分）
   规则: R0001 订单销售汇总
   目标表: slprd.dwb_product_center_tmp1（中间表）
   来源表:
     - sdord.dwd_order_detail_f dod
   粒度: 输入=一条订单商品明细, 输出=一个商品, 多行聚合
   写入方式: truncate_table
   设计意图: 将订单明细按商品粒度聚合，收口为每商品一行的销售指标
   =====================================================
   假设说明:
   - 订单日期字段在 ts.json design_logic 中仅写"订单日期"，未给出具体字段名；
     本脚本按 DWS 字段命名规范（_date 后缀 = DATE 类型）假设为 order_date。
     若源表实际为 create_time / order_time 等其它字段，请相应替换。
   ===================================================== */

SELECT
    dod.product_id AS product_id,                              /* 分组键/业务主键 */
    /* 累计销量: 按 product_id 汇总 SUM(qty) */
    COALESCE(SUM(dod.qty), 0) AS total_sales_qty,
    /* 累计销售额: 按 product_id 汇总 SUM(real_price * qty) */
    COALESCE(SUM(dod.real_price * dod.qty), 0) AS total_sales_amount,
    /* 购买人数: 按 product_id 去重计数 user_id */
    COUNT(DISTINCT dod.user_id) AS buyer_cnt,
    /* 近30天销量: 按 product_id 汇总近30天 SUM(qty)，无记录返回0 */
    COALESCE(
        SUM(
            CASE
                WHEN dod.order_date >= CURRENT_DATE - INTERVAL '30 day'
                    THEN dod.qty
                ELSE 0
            END
        ),
        0
    ) AS sales_qty_30d,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_detail_f dod
WHERE COALESCE(dod.del_flag, 'N') = 'N'                        /* 排除逻辑删除行 */
GROUP BY dod.product_id;
