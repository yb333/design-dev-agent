-- ============================================================
-- DQ 检查: slprd.dwb_product_center_f
-- 规则: R0003
-- ============================================================

-- 无定制 DQ（ts.json dq_rules 为空）

-- 标准 DQ（脚本自动生成）

-- 主键唯一性（键: product_id）
SELECT product_id, COUNT(*) AS cnt
FROM slprd.dwb_product_center_f
GROUP BY product_id
HAVING COUNT(*) > 1;

-- 审计字段非空
SELECT COUNT(*) AS null_count_del_flag
FROM slprd.dwb_product_center_f
WHERE del_flag IS NULL;
SELECT COUNT(*) AS null_count_crt_cycle_id
FROM slprd.dwb_product_center_f
WHERE crt_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_last_upd_cycle_id
FROM slprd.dwb_product_center_f
WHERE last_upd_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_dw_last_update_date
FROM slprd.dwb_product_center_f
WHERE dw_last_update_date IS NULL;

-- 记录数合理性
SELECT COUNT(*) AS total_count
FROM slprd.dwb_product_center_f;
