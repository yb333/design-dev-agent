# -*- coding: utf-8 -*-
"""数据仓库标准定义（design-dev-shared 公共库）。

放"跨角色共享的标准常量"：assemble_ts（designer 装配）和 precheck（pipe 预检）
都要读同一份标准，所以沉在 shared，避免 shared→design 上翻依赖。

注意：这里只放"标准定义"（数据），不放校验/装配逻辑（逻辑在各自的消费方）。
"""

# 标准审计字段模板（4个固定字段，用于补充缺失的审计字段）
# 源端标准写法；DDL 侧 assemble_ddl.normalize_type 转 varchar(1)
STANDARD_AUDIT_TEMPLATE = {
    "del_flag":            {"type": "nvarchar2(1)",                   "default": "'N'"},
    "crt_cycle_id":        {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "last_upd_cycle_id":   {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "dw_last_update_date": {"type": "timestamp(0) without time zone", "default": "CURRENT_TIMESTAMP"},
}
STANDARD_AUDIT_NAMES = set(STANDARD_AUDIT_TEMPLATE.keys())
