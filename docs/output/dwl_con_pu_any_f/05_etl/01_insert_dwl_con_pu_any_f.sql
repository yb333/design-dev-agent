/* =====================================================
   ETL 转换脚本
   步骤: 1
   目标表: fin_dwl_cnb.dwl_con_pu_any_f
   来源表:
     - fin_dwl_cnb.dwl_con_pu_mtr_f (合同pu指标表，主表)
     - fin_dwl_cnb.dwl_con_any_f (合同分析表)
     - fin_dwb_cnb.dwb_inv_head_i (发票头表，CTE内联)
     - fin_dwb_cnb.dwb_inv_cre_i (发票核销表，CTE内联)
     - fin_dwl_cnb.dwl_inv_mtr_i (发票指标表，预聚合)
     - dwrdim_dw1.dwr_dim_pu_d (pu维表，取最新有效行)
   执行频率: 全量覆盖
   说明:
     1. CTE afr_inv 获取非洲发票排除范围
     2. CTE inv_mtr_agg 预聚合发票指标（排除非洲发票）
     3. CTE pu_latest 取pu维度最新有效行
     4. 主查询基于合同pu指标表行转列，LEFT JOIN各CTE和关联表
   ===================================================== */

/* 全量覆盖：先清空目标表 */
TRUNCATE TABLE fin_dwl_cnb.dwl_con_pu_any_f;

/* CTE: 非洲发票排除范围 */
WITH afr_inv AS (
    SELECT
        inv.inv_id,
        inv.contract_no
    FROM fin_dwb_cnb.dwb_inv_head_i inv
    INNER JOIN fin_dwb_cnb.dwb_inv_cre_i cre
        ON inv.inv_id = cre.inv_id
    WHERE inv.company IN ('1001', '1002')
        AND inv.inv_p_flag = 2
        AND cre.app_flag = 0
        AND cre.p_flag = 1
),

/* CTE: 发票指标预聚合（按合同+pu粒度收敛，排除非洲发票） */
inv_mtr_agg AS (
    SELECT
        im.contract_no,
        im.pu_id,
        im.contract_id,
        COALESCE(SUM(im.inv_inst_amt_usd), 0) AS inv_tol_amt_usd,
        COALESCE(SUM(im.inv_inst_amt_rmb), 0) AS inv_tol_amt_rmb
    FROM fin_dwl_cnb.dwl_inv_mtr_i im
    WHERE im.del_flag = 'N'
        AND im.inv_flag IN ('inv_in', 'inv_out')
        AND NOT EXISTS (
            SELECT 1
            FROM afr_inv app
            WHERE im.inv_id = app.inv_id
                AND im.contract_no = app.contract_no
        )
    GROUP BY im.contract_no, im.pu_id, im.contract_id
),

/* CTE: pu维度取最新有效行（SCD模式） */
pu_latest AS (
    SELECT
        pu.pu_id,
        pu.pu_key,
        ROW_NUMBER() OVER (PARTITION BY pu.pu_id ORDER BY pu.scd_active_end_date DESC) AS rn
    FROM dwrdim_dw1.dwr_dim_pu_d pu
    WHERE pu.del_flag = 'N'
        AND pu.scd_active_ind = 1
        AND pu.scd_active_end_date >= CURRENT_DATE
)

/* 主查询: 行转列 + 关联 */
INSERT INTO fin_dwl_cnb.dwl_con_pu_any_f (
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
)
SELECT
    t.contract_no,
    t.contract_id,
    t.contrcat_key,
    t.pu_id,
    t.currency_code,
    /* 行转列: fbt_0001 → 设备订货金额 */
    SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN COALESCE(t.rpt_value_usd, 0) ELSE 0 END) AS equip_org_amt_usd,
    SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN COALESCE(t.rpt_value_rmb, 0) ELSE 0 END) AS equip_org_amt_rmb,
    /* 行转列: fbt_0002 → 设备收入金额 */
    SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN COALESCE(t.rpt_value_rmb, 0) ELSE 0 END) AS equip_cfm_amt_rmb,
    SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN COALESCE(t.rpt_value_usd, 0) ELSE 0 END) AS equip_cfm_amt_usd,
    COALESCE(f.proj_key, 0) AS proj_key,
    COALESCE(im_agg.inv_tol_amt_usd, 0) AS inv_tol_amt_usd,
    COALESCE(im_agg.inv_tol_amt_rmb, 0) AS inv_tol_amt_rmb,
    COALESCE(pl.pu_key, 0) AS pu_key,
    /* 审计字段 */
    'N',                                          /* del_flag */
    '${P_CYCLE_ID}',                              /* crt_cycle_id */
    '${P_CYCLE_ID}',                              /* last_upd_cycle_id */
    CURRENT_TIMESTAMP                             /* dw_last_update_date */
FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
/* 关联合同分析表: contrcat_key唯一，直接关联 */
LEFT JOIN fin_dwl_cnb.dwl_con_any_f f
    ON t.contrcat_key = f.contract_key
    AND f.del_flag = 'N'
/* 关联发票指标聚合: 按contract_id+pu_id收敛后关联 */
LEFT JOIN inv_mtr_agg im_agg
    ON t.contract_id = im_agg.contract_id
    AND t.pu_id = im_agg.pu_id
/* 关联pu维度: 取最新有效行 */
LEFT JOIN pu_latest pl
    ON t.pu_id = pl.pu_id
    AND pl.rn = 1
WHERE t.del_flag = 'N'
GROUP BY
    t.contract_no,
    t.contract_id,
    t.contrcat_key,
    t.pu_id,
    t.currency_code,
    f.proj_key,
    im_agg.inv_tol_amt_usd,
    im_agg.inv_tol_amt_rmb,
    pl.pu_key;
