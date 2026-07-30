/* =====================================================
   表名: fin_dwl_cnb.dwl_con_pu_any_f
   中文名: 合同pu分析表
   类型: 事实表
   步骤: 1
   分布键: contract_id, pu_id
   逻辑集群: LC_DW1
   责任人: zhangsan
   创建时间: 2026-04-14
   说明: 基于合同pu指标表行转列，关联合同分析表、发票指标表（排除非洲发票）和pu维表，组装合同+pu粒度的分析宽表
   ===================================================== */

CREATE TABLE IF NOT EXISTS fin_dwl_cnb.dwl_con_pu_any_f (
    contract_no              NVARCHAR(500),              /* 合同号 */
    contract_id              NUMERIC,                    /* 合同id */
    contrcat_key             NUMERIC,                    /* 合同key */
    pu_id                    NUMERIC,                    /* pu的id */
    tc_code                  NVARCHAR(30),               /* 交易币种 */
    equip_org_amt_usd        NUMERIC(38,10),             /* 设备订货usd金额 */
    equip_org_amt_rmb        NUMERIC(38,10),             /* 设备订货rmb金额 */
    equip_cfm_amt_rmb        NUMERIC(38,10),             /* 设备收入rmb金额 */
    equip_cfm_amt_usd        NUMERIC(38,10),             /* 设备收入usd金额 */
    proj_key                 NUMERIC,                    /* 项目key */
    inv_tol_amt_usd          NUMERIC(38,10),             /* 开票usd金额 */
    inv_tol_amt_rmb          NUMERIC(38,10),             /* 开票rmb金额 */
    pu_key                   NUMERIC,                    /* pu的key */
    /* 审计字段 */
    del_flag                 NVARCHAR(1),
    crt_cycle_id             BIGINT,
    last_upd_cycle_id        BIGINT,
    dw_last_update_date      TIMESTAMP(0) WITHOUT TIME ZONE
)
TO GROUP "LC_DW1";

/* 表注释 */
COMMENT ON TABLE fin_dwl_cnb.dwl_con_pu_any_f IS '合同pu分析表';

/* 业务字段注释 */
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.contract_no IS '合同号';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.contract_id IS '合同id';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.contrcat_key IS '合同key';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.pu_id IS 'pu的id';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.tc_code IS '交易币种';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_org_amt_usd IS '设备订货usd金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_org_amt_rmb IS '设备订货rmb金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_cfm_amt_rmb IS '设备收入rmb金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.equip_cfm_amt_usd IS '设备收入usd金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.proj_key IS '项目key';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.inv_tol_amt_usd IS '开票usd金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.inv_tol_amt_rmb IS '开票rmb金额';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.pu_key IS 'pu的key';

/* 审计字段注释 */
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.del_flag IS '删除标识: Y-已删除, N-正常';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.crt_cycle_id IS '创建批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.last_upd_cycle_id IS '最后更新批次ID';
COMMENT ON COLUMN fin_dwl_cnb.dwl_con_pu_any_f.dw_last_update_date IS '数仓最后更新时间';
