"""标准常量接入（单一来源：design-dev-shared/scripts/dws_standards.py）。

审计字段有标准写法：不管 mapping 写没写、写的什么类型，审计字段类型就是
固定的——断言体系读同一份标准做豁免与校验，不在 eval 里复制第二份真相。
"""

from __future__ import annotations

import sys
from pathlib import Path

_V2_DIR = Path(__file__).resolve().parent
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

# shared 脚本目录（repo 源优先，与 pipeline.SHARED_REFS 同规则；此处自算避免 import 环）
_REPO_SHARED = Path(__file__).resolve().parents[2] / "skills" / "design-dev-shared" / "scripts"
_GLOBAL_SHARED = Path.home() / ".config" / "opencode" / "skills" / "design-dev-shared" / "scripts"
SHARED_SCRIPTS = _REPO_SHARED if _REPO_SHARED.exists() else _GLOBAL_SHARED

# 兜底副本（shared 不可导入时用；结构必须与 dws_standards 保持一致）
_FALLBACK_AUDIT = {
    "del_flag": {"type": "nvarchar2(1)", "default": "'N'"},
    "crt_cycle_id": {"type": "bigint", "default": "'${P_CYCLE_ID}'"},
    "last_upd_cycle_id": {"type": "bigint", "default": "'${P_CYCLE_ID}'"},
    "dw_last_update_date": {"type": "timestamp(0) without time zone", "default": "CURRENT_TIMESTAMP"},
}

try:
    _sys_path = str(SHARED_SCRIPTS)
    if _sys_path not in sys.path:
        sys.path.insert(0, _sys_path)
    from dws_standards import STANDARD_AUDIT_TEMPLATE, STANDARD_AUDIT_NAMES  # type: ignore
except Exception:  # noqa: BLE001 — shared 缺失时兜底，评测仍可跑
    STANDARD_AUDIT_TEMPLATE = _FALLBACK_AUDIT
    STANDARD_AUDIT_NAMES = set(_FALLBACK_AUDIT)


def norm_type(t: str) -> str:
    """类型归一比对：小写去空格（timestamp(0) without time zone 两边一致可比）。"""
    return (t or "").strip().lower().replace(" ", "")


def standard_audit_type(col: str) -> str:
    """某审计字段的标准类型（归一后）；非审计字段返回空串。"""
    info = STANDARD_AUDIT_TEMPLATE.get(col) or STANDARD_AUDIT_TEMPLATE.get(col.lower())
    return norm_type(info["type"]) if info else ""
