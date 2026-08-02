/* =====================================================
   表名: slord.dwb_order_center_shop_tmp3
   规则: R0003 - 店铺画像聚合
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 收口按 shop_id 聚合的店铺历史订单数指标。中间表粒度=一个店铺一行， 以 shop_id 为关联键供主规则 JOIN。

   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_shop_tmp3 (
    shop_history_order_cnt int,  /* 店铺历史订单数 */
    /* 审计字段 */
    del_flag               NVARCHAR(1),
    crt_cycle_id           BIGINT,
    last_upd_cycle_id      BIGINT,
    dw_last_update_date    TIMESTAMP(0)
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(order_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slord.dwb_order_center_shop_tmp3 IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_shop_tmp3.shop_history_order_cnt IS '店铺历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp3.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp3.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp3.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp3.dw_last_update_date IS '数仓最后更新时间';
