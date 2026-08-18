"""checks.yaml 解析与校验。

每个用例配一份 checks.yaml。分工（与 golden 的边界）：
- checks.yaml：人钉死的**强契约值断言**（rules_expected/business_key/load_mode_expected）
  与**禁止式**（field_not_mapped_from）；默认结构断言不写（默认全开，只在关时写 false）
- golden/：产出的结构事实（分布键/中间表/规则数据流等）自动指纹比对，不进 checks

校验原则：**未知键 fail loud**——写错键名（typo）直接报错，绝不静默跳过
（评测系统最毒的失效模式是"以为测了实际没测"）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 各段合法键（与断言层实际消费的键一一对应；加新断言时同步这里）
CASE_KEYS = {"name", "rules_expected"}
ARTIFACTS_KEYS = {
    "ts_json_top_keys",
    "audit_fields_count",
    "audit_field_names",
    "each_rule_has_load_mode",
    "ddl_rollback_paired",
    "no_select_star_in_view",
}
DESIGN_KEYS = {
    "business_key",
    "field_targets_cover_rs_input",
    "field_targets_no_cross_rule_dup",
    "load_mode_valid",
    "join_safety_strategy_when_not_unique",
    "segmentation_reason_when_segmented",
    "source_tables_required",
    "field_not_mapped_from",
    "load_mode_expected",
}
SCORING_KEYS = {  # 扣分类别（scoring.py DEFAULT_WEIGHTS 的键），值=该类单项扣分
    "design_contract",
    "self_consistency",
    "field_caliber",
    "structure_std",
    "pipeline_stage",
    "artifact",
    "design_default",
    "code_default",
}
CODE_RULE_KEYS = {
    "fields_required",
    "join_tables",
    "group_by_granularity",
    "where_must_contain_del_flag",
    "case_when_must_have_else",
    "no_select_star",
    "audit_fields_in_select",
}


@dataclass
class ChecksConfig:
    """单个用例的断言配置。"""

    case_name: str = ""
    rules_expected: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    design: dict[str, Any] = field(default_factory=dict)
    code: dict[str, Any] = field(default_factory=dict)
    scoring: dict[str, Any] = field(default_factory=dict)


def _validate_section(section: str, data: dict, allowed: set[str]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(
            f"checks.yaml {section} 段未知键: {sorted(unknown)}（可用键: {sorted(allowed)}）。"
            f"修正拼写或删除——未知键说明断言没在跑，评测结果不可信"
        )


def load_checks(checks_path: Path) -> ChecksConfig:
    """从 checks.yaml 加载配置并校验键名。

    文件不存在返回空配置（用各层默认断言）。
    键名不在白名单 → ValueError（fail loud，防 typo 静默失效）。
    """
    if not checks_path.exists():
        return ChecksConfig()

    import yaml

    raw = yaml.safe_load(checks_path.read_text(encoding="utf-8")) or {}
    case = raw.get("case", {})
    _validate_section("case", case, CASE_KEYS)

    artifacts = raw.get("artifacts", {})
    _validate_section("artifacts", artifacts, ARTIFACTS_KEYS)

    design = raw.get("design", {})
    _validate_section("design", design, DESIGN_KEYS)

    code = raw.get("code", {})
    if not isinstance(code, dict):
        raise ValueError(f"checks.yaml code 段必须是 {{规则编码: 断言}} 映射，当前: {type(code).__name__}")
    for rule_code, rule_cfg in code.items():
        if not isinstance(rule_cfg, dict):
            raise ValueError(f"checks.yaml code.{rule_code} 必须是映射，当前: {type(rule_cfg).__name__}")
        _validate_section(f"code.{rule_code}", rule_cfg, CODE_RULE_KEYS)

    scoring = raw.get("scoring", {})
    _validate_section("scoring", scoring, SCORING_KEYS)

    return ChecksConfig(
        case_name=case.get("name", ""),
        rules_expected=case.get("rules_expected", []),
        artifacts=artifacts,
        design=design,
        code=code,
        scoring=scoring,
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
