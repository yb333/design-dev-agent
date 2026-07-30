/* =====================================================
   视图名: fin_dwl_cnb.dwl_con_pu_any_i
   中文名: 合同pu分析表-消费视图
   类型: 消费视图
   步骤: 2
   责任人: zhangsan
   创建时间: 2026-04-14
   说明: 封装消费视图，对外提供统一查询接口
   ===================================================== */

CREATE OR REPLACE VIEW fin_dwl_cnb.dwl_con_pu_any_i AS
SELECT
    contract_no,
    contract_id,
    contrcat_key,
    pu_id,
    tc_code,
    equip_org_amt_usd,
    equip_org_amt_rmb,
    equip_cfm_amt_rmb,
    equip_cfm_amt_usd,
    proj_key,
    inv_tol_amt_usd,
    inv_tol_amt_rmb,
    pu_key,
    del_flag,
    crt_cycle_id,
    last_upd_cycle_id,
    dw_last_update_date
FROM fin_dwl_cnb.dwl_con_pu_any_f;

/* 视图注释 */
COMMENT ON VIEW fin_dwl_cnb.dwl_con_pu_any_i IS '合同pu分析表-消费视图';
