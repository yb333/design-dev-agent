-- ============================================================
-- DQ 检查: slord.dwb_user_behavior_f
-- 规则: R0004
-- ============================================================

-- 定制 DQ（来自 RS/ts.json，2 条，由 coder 编写 SQL）
-- coder 读取 ts.json 的 dq_rules，理解每条规则的检查意图，编写对应的 DQ SQL

-- TODO [behavior_id 全局唯一性检查]
--   类型: uniqueness
--   对象: behavior_id
--   阈值: 重复行数 = 0
--   coder 请根据上述信息编写 DQ 检查 SQL

-- TODO [场景来源完整性检查]
--   类型: completeness
--   对象: behavior_id
--   阈值: F 表行数 ≈ tmp1 + tmp2 + tmp3 行数(允许 ±1‰ 误差)
--   coder 请根据上述信息编写 DQ 检查 SQL

-- 标准 DQ（脚本自动生成）

-- 主键唯一性（键: behavior_id）
SELECT behavior_id, COUNT(*) AS cnt
FROM slord.dwb_user_behavior_f
GROUP BY behavior_id
HAVING COUNT(*) > 1;

-- 审计字段非空
SELECT COUNT(*) AS null_count_del_flag
FROM slord.dwb_user_behavior_f
WHERE del_flag IS NULL;
SELECT COUNT(*) AS null_count_crt_cycle_id
FROM slord.dwb_user_behavior_f
WHERE crt_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_last_upd_cycle_id
FROM slord.dwb_user_behavior_f
WHERE last_upd_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_dw_last_update_date
FROM slord.dwb_user_behavior_f
WHERE dw_last_update_date IS NULL;

-- 记录数合理性
SELECT COUNT(*) AS total_count
FROM slord.dwb_user_behavior_f;
