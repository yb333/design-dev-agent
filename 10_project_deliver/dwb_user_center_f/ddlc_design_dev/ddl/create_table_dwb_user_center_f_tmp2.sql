/* =====================================================
   表名: slusr.dwb_user_center_f_tmp2
   规则: R0002 - RFM 评分中间表
   分布键: user_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-05
   说明: 基于订单聚合指标用 NTILE(5) 窗口函数跨全量用户打分，产出 RFM 三维分数与价值分层
   ===================================================== */

CREATE TABLE IF NOT EXISTS slusr.dwb_user_center_f_tmp2 (
    rfm_r_score int,
    rfm_f_score int,
    rfm_m_score int,
    rfm_segment varchar(20),
    /* 审计字段 */
    del_flag    NVARCHAR(1),
    crt_cycle_id BIGINT,
    last_upd_cycle_id BIGINT,
    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(user_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE slusr.dwb_user_center_f_tmp2 IS '用户中心宽表';

COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.rfm_r_score IS 'RFM-R值';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.rfm_f_score IS 'RFM-F值';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.rfm_m_score IS 'RFM-M值';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.rfm_segment IS '用户价值分层';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN slusr.dwb_user_center_f_tmp2.dw_last_update_date IS '数仓最后更新时间';
