-- ============================================================
-- DQ 检查: slusr.dwb_user_center_f
-- 规则: R0004
-- ============================================================

-- 无定制 DQ（ts.json dq_rules 为空）

-- 标准 DQ（脚本自动生成）

-- 主键唯一性（键: user_id）
SELECT user_id, COUNT(*) AS cnt
FROM slusr.dwb_user_center_f
GROUP BY user_id
HAVING COUNT(*) > 1;

-- 审计字段非空
SELECT COUNT(*) AS null_count_del_flag
FROM slusr.dwb_user_center_f
WHERE del_flag IS NULL;
SELECT COUNT(*) AS null_count_crt_cycle_id
FROM slusr.dwb_user_center_f
WHERE crt_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_last_upd_cycle_id
FROM slusr.dwb_user_center_f
WHERE last_upd_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_dw_last_update_date
FROM slusr.dwb_user_center_f
WHERE dw_last_update_date IS NULL;

-- 记录数合理性
SELECT COUNT(*) AS total_count
FROM slusr.dwb_user_center_f;
