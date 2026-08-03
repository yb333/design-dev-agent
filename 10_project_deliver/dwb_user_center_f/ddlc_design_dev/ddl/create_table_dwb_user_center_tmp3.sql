/* =====================================================
   表名: slusr.dwb_user_center_tmp3
   规则: R0003 - 行为汇总中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-03
   说明: 对 dwd_user_behavior_f 按 user_id 聚合浏览/收藏/加购行为指标，供最终装配规则引用。粒度从行为明细收敛到用户。
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_tmp3 (
    total_pv_cnt      int,  /* 浏览次数 */
    total_collect_cnt int,  /* 收藏次数 */
    total_cart_cnt    int,  /* 加购次数 */
    /* 审计字段 */
    del_flag          NVARCHAR(1),
    crt_cycle_id      BIGINT,
    last_upd_cycle_id BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_tmp3 IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_tmp3.total_pv_cnt IS '浏览次数';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.total_collect_cnt IS '收藏次数';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.total_cart_cnt IS '加购次数';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_tmp3.dw_last_update_date IS '数仓最后更新时间';
