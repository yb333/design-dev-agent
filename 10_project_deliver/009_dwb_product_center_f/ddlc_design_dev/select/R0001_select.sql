/* =====================================================
   规则号: R0001
   规则名: 商品销售汇总中间表
   目标表: slprd.dwb_product_sales_tmp1（中间表）
   粒度: 多行/商品(订单明细) → 一行/商品(按 product_id 收敛)
   设计意图: 把订单明细按 product_id 聚合到商品粒度，
            产出累计销量/累计销售额/购买人数/近30天销量，
            供 R0003 按 product_id 安全关联宽表，避免主表行数发散。
   源表: sdord.dwd_order_detail_f (别名 dod)
   关联安全: GROUP BY product_id 收敛后聚合，product_id 唯一
   ===================================================== */

/* 过滤说明:
   - design_logic 明确为"全量订单"，故不臆造业务状态过滤
     (源表订单状态字段名/枚举值未在切片中确认，保持全量聚合)。
   - 仅保留数仓标准软删除过滤(del_flag='N')，属技术层面，
     不改变业务"全量有效订单"口径。
   - 源字段假设(切片 source_fields 为空，按 design_logic 推断):
     qty=销售数量, real_price=实付单价, user_id=买家ID, order_time=下单时间。
*/

SELECT
    dod.product_id AS product_id,
    COALESCE(SUM(dod.qty), 0) AS total_sales_qty,
    COALESCE(SUM(dod.real_price * dod.qty), 0) AS total_sales_amount,
    COUNT(DISTINCT dod.user_id) AS buyer_cnt,
    COALESCE(
        SUM(
            CASE
                WHEN dod.order_time >= CURRENT_DATE - INTERVAL '30 day'
                    THEN dod.qty
                ELSE 0
            END
        ), 0
    ) AS sales_qty_30d,
    'N' AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM sdord.dwd_order_detail_f dod
WHERE COALESCE(dod.del_flag, 'N') = 'N'
GROUP BY dod.product_id;
