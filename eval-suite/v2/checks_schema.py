"""checks.yaml 解析与校验。

每个用例配一份 checks.yaml，定义断言清单。P1 只用到 artifacts 段；
design/code 段留空或占位，引擎遇到未实现的层标 SKIP。

结构示例见 eval-suite/v2/checks.example.yaml。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChecksConfig:
    """单个用例的断言配置。"""

    case_name: str = ""
    target_table: str = ""
    rules_expected: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    design: dict[str, Any] = field(default_factory=dict)
    code: dict[str, Any] = field(default_factory=dict)
    # P3 才用
    data_diff: dict[str, Any] = field(default_factory=dict)
    style: dict[str, Any] = field(default_factory=dict)


def load_checks(checks_path: Path) -> ChecksConfig:
    """从 checks.yaml 加载配置。

    文件不存在时返回空配置（P1 允许无 checks.yaml，产物层用默认断言）。
    """
    if not checks_path.exists():
        return ChecksConfig()

    import yaml

    raw = yaml.safe_load(checks_path.read_text(encoding="utf-8")) or {}
    case = raw.get("case", {})
    return ChecksConfig(
        case_name=case.get("name", ""),
        target_table=case.get("target_table", ""),
        rules_expected=case.get("rules_expected", []),
        artifacts=raw.get("artifacts", {}),
        design=raw.get("design", {}),
        code=raw.get("code", {}),
        data_diff=raw.get("data_diff", {}),
        style=raw.get("style", {}),
    )


# 产物层默认断言（checks.yaml 没配 artifacts 段时用这套）
DEFAULT_ARTIFACT_CHECKS = {
    "ts_json_top_keys": ["version", "meta", "design", "rules", "data_flow"],
    "audit_fields_count": 4,
    "audit_field_names": [
        "del_flag",
        "crt_cycle_id",
        "last_upd_cycle_id",
        "dw_last_update_date",
    ],
    "each_rule_has_load_mode": True,
    "ddl_rollback_paired": True,
    "no_select_star_in_view": True,
}
