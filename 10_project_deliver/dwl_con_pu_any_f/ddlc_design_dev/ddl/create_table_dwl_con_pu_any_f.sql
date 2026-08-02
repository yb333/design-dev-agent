/* =====================================================
   表名: fin_dwl_cnb.dwl_con_pu_any_f
   规则: R0001 - 合同pu分析表写入
   分布键: contract_id, pu_id
   逻辑集群: LC_DW1
   生成时间: 2026-08-02
   说明: 主查询：将主表 rpt_code 指标行转列收敛为4个金额列，LEFT JOIN 合同分析表取项目key、 收敛后的发票指标表（排除非洲发票）取发票总额、pu维表（取最新有效行）取pu_key， 按合同+pu粒度写入分析宽表。
   ===================================================== */

CREATE TABLE IF NOT EXISTS fin_dwl_cnb.dwl_con_pu_any_f (
    contract_no         nvarchar(500),  /* 合同号 */
    contract_id         numeric,  /* 合同ID */
    pu_id               numeric,  /* puID */
    tc_code             nvarchar(30),  /* 币种代码 */
    equip_org_amt_usd   numeric(38,10),  /* 设备订货USD金额 */
    equip_org_amt_rmb   numeric(38,10),  /* 设备订货RMB金额 */
    equip_cfm_amt_rmb   numeric(38,10),  /* 设备收入RMB金额 */
    equip_cfm_amt_usd   numeric(38,10),  /* 设备收入USD金额 */
    proj_key            numeric,  /* 项目key */
    inv_tol_amt_usd     numeric(38,10),  /* 发票总额USD */
    inv_tol_amt_rmb     numeric(38,10),  /* 发票总额RMB */
    pu_key              numeric,  /* pu key */
    del_flag            nvarchar(1),  /* 删除标识 */
    crt_cycle_id        bigint,  /* 创建批次ID */
    last_upd_cycle_id   bigint,  /* 最后更新批次ID */
    dw_last_update_date timestamp(0) without time zone,  /* 数仓最后更新时间 */
    /* 审计字段 */
    del_flag            nvarchar(1),
    crt_cycle_id        bigint,
    last_upd_cycle_id   bigint,
    dw_last_update_date timestamp(0) without time zone
)
WITH (
    ORIENTATION = COLUMN,
    COMPRESSION = LOW
)
DISTRIBUTE BY HASH(contract_id, pu_id)
TO GROUP "LC_DW1";

COMMENT ON TABLE fin_dwl_cnb.dwl_con_pu_any_f IS '合同pu分析表';

COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.contract_no IS '合同号';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.contract_id IS '合同ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.pu_id IS 'puID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.tc_code IS '币种代码';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_org_amt_usd IS '设备订货USD金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_org_amt_rmb IS '设备订货RMB金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_cfm_amt_rmb IS '设备收入RMB金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_cfm_amt_usd IS '设备收入USD金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.proj_key IS '项目key';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.inv_tol_amt_usd IS '发票总额USD';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.inv_tol_amt_rmb IS '发票总额RMB';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.pu_key IS 'pu key';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.del_flag IS '删除标识';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.dw_last_update_date IS '数仓最后更新时间';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.dw_last_update_date IS '数仓最后更新时间';
