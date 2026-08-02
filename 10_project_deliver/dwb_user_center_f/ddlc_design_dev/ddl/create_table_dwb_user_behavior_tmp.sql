/* =====================================================
   表名: slusr.dwb_user_behavior_tmp
   规则: R0002 - 行为画像中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 将用户行为事实表按用户聚合收口为用户粒度的行为画像，提供浏览/收藏/加购行为指标，支撑转化率派生计算
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_behavior_tmp (
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

COMMENT ON TABLE slusr.dwb_user_behavior_tmp IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.total_pv_cnt IS '浏览次数';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.total_collect_cnt IS '收藏次数';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.total_cart_cnt IS '加购次数';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_behavior_tmp.dw_last_update_date IS '数仓最后更新时间';
