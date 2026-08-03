/* =====================================================
   表名: slord.dwb_order_center_shop_tmp1
   规则: R0003 - 店铺画像中间表
   分布键: order_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 收口按 shop_id 聚合的店铺历史订单数(先聚合再关联)，输出店铺粒度，避免发散订单粒度。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slord.dwb_order_center_shop_tmp1 (
    shop_id                bigint,  /* 店铺ID */
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

COMMENT ON TABLE slord.dwb_order_center_shop_tmp1 IS '订单中心宽表';

COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.shop_id IS '店铺ID';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.shop_history_order_cnt IS '店铺历史订单数';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slord.dwb_order_center_shop_tmp1.dw_last_update_date IS '数仓最后更新时间';
