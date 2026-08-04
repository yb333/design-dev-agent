-- ============================================================
-- DQ 检查: slmar.dwb_marketing_center_f
-- 规则: R0002
-- ============================================================

-- 无定制 DQ（ts.json dq_rules 为空）

-- 标准 DQ（脚本自动生成）

-- 主键唯一性（键: activity_id）
SELECT activity_id, COUNT(*) AS cnt
FROM slmar.dwb_marketing_center_f
GROUP BY activity_id
HAVING COUNT(*) > 1;

-- 审计字段非空
SELECT COUNT(*) AS null_count_del_flag
FROM slmar.dwb_marketing_center_f
WHERE del_flag IS NULL;
SELECT COUNT(*) AS null_count_crt_cycle_id
FROM slmar.dwb_marketing_center_f
WHERE crt_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_last_upd_cycle_id
FROM slmar.dwb_marketing_center_f
WHERE last_upd_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_dw_last_update_date
FROM slmar.dwb_marketing_center_f
WHERE dw_last_update_date IS NULL;

-- 记录数合理性
SELECT COUNT(*) AS total_count
FROM slmar.dwb_marketing_center_f;
