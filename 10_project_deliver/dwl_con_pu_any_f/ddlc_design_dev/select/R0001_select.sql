/* =====================================================
   R0001: 合同pu分析表写入
   目标表: fin_dwl_cnb.dwl_con_pu_any_f
   设计意图: 主表 rpt_code 指标行转列收敛为4个金额列，
     LEFT JOIN 合同分析表取项目key、收敛后的发票指标表(排除非洲发票)取发票总额、
     pu维表(取最新有效行)取pu_key，按 合同+pu 粒度写入分析宽表。
   粒度: (contract_id, pu_id, rpt_code) -> (contract_id, pu_id) 行转列收敛
   ===================================================== */
WITH
/* CTE inv_agg: 发票指标表按 合同+pu 收敛求和（排除非洲发票），避免 JOIN 发散 */
inv_agg AS (
    SELECT
        inv_mtr.contract_id AS contract_id,
        inv_mtr.pu_id AS pu_id,
        COALESCE(SUM(inv_mtr.inv_inst_amt_usd), 0) AS inv_tol_amt_usd,
        COALESCE(SUM(inv_mtr.inv_inst_amt_rmb), 0) AS inv_tol_amt_rmb
    FROM fin_dwl_cnb.dwl_inv_mtr_i inv_mtr
    WHERE inv_mtr.del_flag = 'N'
      AND inv_mtr.region <> 'AFRICA'   /* 排除非洲发票: 字段名 region / 枚举值 'AFRICA' 为基于模板的假设, 需业务确认 */
    GROUP BY inv_mtr.contract_id, inv_mtr.pu_id
)

/* 主查询: 主表 rpt_code 行转列 + 安全 JOIN（粒度对齐后关联） */
SELECT
    t.contract_no AS contract_no,
    t.contract_id AS contract_id,
    t.pu_id AS pu_id,
    t.tc_code AS tc_code,
    COALESCE(SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_usd ELSE 0 END), 0) AS equip_org_amt_usd,
    COALESCE(SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_rmb ELSE 0 END), 0) AS equip_org_amt_rmb,
    COALESCE(SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_rmb ELSE 0 END), 0) AS equip_cfm_amt_rmb,
    COALESCE(SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_usd ELSE 0 END), 0) AS equip_cfm_amt_usd,
    COALESCE(f.proj_key, 0) AS proj_key,
    COALESCE(inv_agg.inv_tol_amt_usd, 0) AS inv_tol_amt_usd,
    COALESCE(inv_agg.inv_tol_amt_rmb, 0) AS inv_tol_amt_rmb,
    COALESCE(pu.pu_key, 0) AS pu_key,
    IF(t.status = '已作废', 'Y', 'N') AS del_flag,
    '${P_CYCLE_ID}' AS crt_cycle_id,
    '${P_CYCLE_ID}' AS last_upd_cycle_id,
    CURRENT_TIMESTAMP AS dw_last_update_date
FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
LEFT JOIN fin_dwl_cnb.dwl_con_any_f f
    ON t.contract_key = f.contract_key
    AND f.del_flag = 'N'
LEFT JOIN inv_agg
    ON t.contract_id = inv_agg.contract_id
    AND t.pu_id = inv_agg.pu_id
LEFT JOIN (
    /* pu维表取最新有效行（关联安全策略: 维度表含历史版本，按生效日期降序取最新一条） */
    SELECT
        pu_dim.pu_id AS pu_id,
        pu_dim.pu_key AS pu_key,
        ROW_NUMBER() OVER (PARTITION BY pu_dim.pu_id ORDER BY pu_dim.effective_dt DESC NULLS LAST) AS _rn
    FROM dwrdim_dw1.dwr_dim_pu_d pu_dim
    WHERE pu_dim.del_flag = 'N'
) pu
    ON t.pu_id = pu.pu_id
    AND pu._rn = 1
WHERE t.del_flag = 'N'
GROUP BY
    t.contract_no,
    t.contract_id,
    t.pu_id,
    t.tc_code,
    f.proj_key,
    inv_agg.inv_tol_amt_usd,
    inv_agg.inv_tol_amt_rmb,
    pu.pu_key,
    t.status;
