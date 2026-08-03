-- ============================================================
-- DQ 检查: dws.dwb_trade_order_d
-- 规则: R0001
-- ============================================================

-- 无定制 DQ（ts.json dq_rules 为空）

-- 标准 DQ（脚本自动生成）

-- 主键唯一性（键: order_id）
SELECT order_id, COUNT(*) AS cnt
FROM dws.dwb_trade_order_d
GROUP BY order_id
HAVING COUNT(*) > 1;

-- 审计字段非空
SELECT COUNT(*) AS null_count_del_flag
FROM dws.dwb_trade_order_d
WHERE del_flag IS NULL;
SELECT COUNT(*) AS null_count_crt_cycle_id
FROM dws.dwb_trade_order_d
WHERE crt_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_last_upd_cycle_id
FROM dws.dwb_trade_order_d
WHERE last_upd_cycle_id IS NULL;
SELECT COUNT(*) AS null_count_dw_last_update_date
FROM dws.dwb_trade_order_d
WHERE dw_last_update_date IS NULL;

-- 记录数合理性
SELECT COUNT(*) AS total_count
FROM dws.dwb_trade_order_d;
