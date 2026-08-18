"""design 质量断言：检查 designer 的设计决策。

检查对象：design_decisions.yaml + ts.json 的 design/rules/tables 段。
断言来自 checks.yaml 的 design 段。

断言类型：
- business_key：严格相等（对错问题）
- field_targets 覆盖 rs_input：集合相等
- field_targets 不跨规则重复：唯一性
- load_mode 合法：枚举
- incremental 条件存在：load_mode≠truncate_table 时必须有
- join_safety strategy 非空：join_key_unique=false 时
- source_tables 识别：集合包含
- segmentation 自洽：分段时 reason 非空
- field_not_mapped_from：字段不能映射自某表（数据源缺口陷阱用）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 复用 base.py（validators 作为包加载）
_EVAL_SUITE = Path(__file__).resolve().parent.parent
if str(_EVAL_SUITE) not in sys.path:
    sys.path.insert(0, str(_EVAL_SUITE))

from validators.base import CheckResult, CheckStatus  # type: ignore

# 合法 load_mode 枚举
VALID_LOAD_MODES = {
    "truncate_table",
    "no_delete",
    "delete",
    "truncate_partition",
    "truncate_subpartition",
    "merge_into",
}


def run_design_checks(
    output_dir: Path,
    checks: dict | None,
    rs_input: dict | None = None,
    rules_expected: list[str] | None = None,
) -> list[CheckResult]:
    """跑 design 质量断言。

    Args:
        output_dir: ddlc_design_dev 目录。
        checks: checks.yaml 的 design 段（None=无配置，跑默认检查）。
        rs_input: rs_input.json（用来校验 field_targets 覆盖）；None 则跳过覆盖检查。
        rules_expected: case 段的规则集合契约（严格相等；None=不查）。
    """
    cfg = checks or {}
    results: list[CheckResult] = []

    ts_path = output_dir / "ts.json"
    dec_path = output_dir / "_internal" / "design_decisions.yaml"

    if not ts_path.exists():
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.SKIP,
                detail="ts.json 不存在，跳过 design 检查",
            )
        ]

    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 加载 design_decisions（yaml，没有也能跑部分检查）
    dec = _load_yaml(dec_path)

    # 0. rules_expected：规则集合严格相等（方案契约——认可方案里规则数/编码稳定）
    if rules_expected:
        results.extend(_check_rules_expected(ts, rules_expected))

    # 1. business_key（严格相等）
    if "business_key" in cfg:
        results.extend(_check_business_key(ts, cfg["business_key"]))

    # 2. field_targets 覆盖 rs_input
    if rs_input and cfg.get("field_targets_cover_rs_input", True):
        results.extend(_check_field_targets_cover(dec, ts, rs_input))

    # 3. field_targets 不跨规则重复
    if cfg.get("field_targets_no_cross_rule_dup", True):
        results.extend(_check_field_targets_no_dup(dec))

    # 4. load_mode 合法
    if cfg.get("load_mode_valid", True):
        results.extend(_check_load_mode(dec, ts))

    # 5. incremental 条件存在
    results.extend(_check_incremental(dec, ts))

    # 6. join_safety strategy 非空
    if cfg.get("join_safety_strategy_when_not_unique", True):
        results.extend(_check_join_safety(dec))

    # 7. source_tables 识别（集合包含）
    if "source_tables_required" in cfg:
        results.extend(_check_source_tables(ts, cfg["source_tables_required"]))

    # 7.5 load_mode_expected：每规则 load_mode 等于契约值（增量场景用）
    if "load_mode_expected" in cfg:
        results.extend(_check_load_mode_expected(ts, cfg["load_mode_expected"]))

    # 7.6 类型符合输入要求（致命）：ts 表字段基类型 vs mapping 目标类型
    if rs_input and cfg.get("types_match_input", True):
        results.extend(_check_types_match_input(ts, rs_input))

    # 8. segmentation 自洽
    if cfg.get("segmentation_reason_when_segmented", True):
        results.extend(_check_segmentation(dec, ts))

    # 9. field_not_mapped_from（字段不能映射自某表）
    if "field_not_mapped_from" in cfg:
        results.extend(_check_field_not_mapped_from(ts, cfg["field_not_mapped_from"]))

    return results


# ============================================================
# 各断言
# ============================================================


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _check_business_key(ts: dict, expected: list) -> list[CheckResult]:
    actual = ts.get("design", {}).get("business_key", [])
    if not actual:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail="business_key 为空",
            )
        ]
    if set(actual) == set(expected):
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.PASS,
                detail=f"business_key 匹配: {actual}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.FAIL,
            detail=f"business_key 不符: 实际 {actual} ≠ 期望 {expected}",
        )
    ]


def _check_field_targets_cover(dec: dict, ts: dict, rs_input: dict) -> list[CheckResult]:
    """所有规则的 field_targets 并集 == rs_input 的 target_column 全集。"""
    expected = {fm["target_column"] for fm in rs_input.get("field_mappings", []) if fm.get("target_column")}
    if not expected:
        return []

    # 优先从 design_decisions 取（权威），fallback ts.rules
    actual = set()
    dec_rules = dec.get("rules", []) if dec else []
    if dec_rules:
        for r in dec_rules:
            actual.update(r.get("field_targets", []))
    else:
        for r in ts.get("rules", {}).values():
            actual.update(r.get("field_targets", []))

    missing = expected - actual
    extra = actual - expected
    if not missing and not extra:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.PASS,
                detail=f"field_targets 完整覆盖 rs_input ({len(actual)} 字段)",
            )
        ]
    parts = []
    if missing:
        parts.append(f"缺 {sorted(missing)}")
    if extra:
        parts.append(f"多 {sorted(extra)}")
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.FAIL,
            detail=f"field_targets 覆盖不全: {'; '.join(parts)}",
        )
    ]


def _check_field_targets_no_dup(dec: dict) -> list[CheckResult]:
    """同一字段不应出现在多个规则的 field_targets 里。"""
    dec_rules = dec.get("rules", []) if dec else []
    if not dec_rules:
        return []
    seen: dict[str, list[str]] = {}
    for r in dec_rules:
        code = r.get("rule_code", "?")
        for ft in r.get("field_targets", []):
            seen.setdefault(ft, []).append(code)
    dups = {ft: codes for ft, codes in seen.items() if len(codes) > 1}
    if dups:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"field_targets 跨规则重复: {dict(list(dups.items())[:3])}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail="field_targets 无跨规则重复",
        )
    ]


def _check_load_mode(dec: dict, ts: dict) -> list[CheckResult]:
    """每规则 load_mode 合法。"""
    # 从 ts.rules 取（designer 的 load_mode 在 assemble 后落到 ts）
    rules = ts.get("rules", {})
    if not rules:
        return []
    bad = []
    for code, r in rules.items():
        lm = r.get("load_mode")
        if not lm:
            bad.append(f"{code}: 无 load_mode")
        elif lm not in VALID_LOAD_MODES:
            bad.append(f"{code}: load_mode '{lm}' 非法")
    if bad:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"load_mode 问题: {bad}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"load_mode 合法 ({len(rules)} 规则)",
        )
    ]


def _check_incremental(dec: dict, ts: dict) -> list[CheckResult]:
    """增量规则必须有 incremental 段；全量规则不应有。"""
    rules = ts.get("rules", {})
    results = []
    for code, r in rules.items():
        lm = r.get("load_mode", "truncate_table")
        inc = r.get("incremental")
        if lm != "truncate_table":
            # 增量场景：必须有 incremental（key/filter/init_mode 至少有 key）
            if not inc or not inc.get("key"):
                results.append(
                    CheckResult(
                        check_type="design",
                        status=CheckStatus.FAIL,
                        detail=f"{code}: load_mode={lm} 但缺 incremental.key",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_type="design",
                        status=CheckStatus.PASS,
                        detail=f"{code}: 增量配置完整 (key={inc.get('key')})",
                    )
                )
    if not results:
        results.append(
            CheckResult(
                check_type="design",
                status=CheckStatus.PASS,
                detail="无增量规则（全量），incremental 检查不适用",
            )
        )
    return results


def _check_join_safety(dec: dict) -> list[CheckResult]:
    """join_key_unique=false 时 strategy 必须非空。"""
    dec_rules = dec.get("rules", []) if dec else []
    if not dec_rules:
        return []
    bad = []
    checked = 0
    for r in dec_rules:
        for js in r.get("join_safety", []):
            checked += 1
            if not js.get("join_key_unique", True):
                if not js.get("strategy"):
                    bad.append(f"{r.get('rule_code','?')}/{js.get('table','?')}")
    if bad:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"join_key 非唯一但缺 strategy: {bad}",
            )
        ]
    if checked:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.PASS,
                detail=f"join_safety 检查通过 ({checked} 项)",
            )
        ]
    return []


def _check_source_tables(ts: dict, required: list) -> list[CheckResult]:
    """rules 里出现的源表应 ⊇ 期望必须关联的源表。"""
    expected_bare = {t.split(".")[-1] for t in required}
    actual_bare = set()
    for r in ts.get("rules", {}).values():
        for st in r.get("source_tables", []):
            tbl = st.get("table", "")
            if tbl:
                actual_bare.add(tbl)
    missing = expected_bare - actual_bare
    if missing:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"源表识别缺失: {sorted(missing)}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"源表识别完整 ({len(actual_bare)} 表)",
        )
    ]


def _check_types_match_input(ts: dict, rs_input: dict) -> list[CheckResult]:
    """ts 表字段基类型 vs mapping（rs_input）目标类型——"类型满足输入要求"。

    只查双方都有的字段（缺字段由覆盖类断言负责）；比基类型（varchar(50) vs
    varchar(100) 算满足）；audit 字段不在 mapping 范围跳过。
    """
    wanted = {}
    for fm in rs_input.get("field_mappings", []):
        col = (fm.get("target_column") or "").lower()
        typ = (fm.get("target_type") or "").strip()
        if col and typ:
            wanted[col] = typ
    if not wanted:
        return []
    actual: dict[str, str] = {}
    for tdef in (ts.get("tables") or {}).values():
        for f in tdef.get("fields", []):
            col = (f.get("target_field") or "").lower()
            if col:
                actual[col] = (f.get("field_type") or "").strip()
    bad = []
    for col, want in wanted.items():
        got = actual.get(col)
        if not got:
            continue
        base_w = want.lower().split("(")[0].strip()
        base_g = got.lower().split("(")[0].strip()
        if base_w != base_g:
            bad.append(f"{col}: 输入要求 {want} / 实际 {got}")
    if bad:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"类型不符输入要求: {bad[:5]}（→ designer/assembler 类型映射）",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"字段类型符合输入要求 ({len(wanted)} 字段基类型比对)",
        )
    ]


def _check_rules_expected(ts: dict, expected: list) -> list[CheckResult]:
    """规则集合严格相等（编码集合，不序）。"""
    actual = set(ts.get("rules", {}).keys())
    exp = set(expected)
    missing = exp - actual
    extra = actual - exp
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"缺 {sorted(missing)}")
        if extra:
            parts.append(f"多 {sorted(extra)}")
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"规则集不符: {'; '.join(parts)}（实际 {sorted(actual)} ≠ 期望 {sorted(exp)}）",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"规则集匹配 ({len(exp)} 规则: {sorted(exp)})",
        )
    ]


def _check_load_mode_expected(ts: dict, expected: dict) -> list[CheckResult]:
    """每规则 load_mode 等于契约值（如增量案例 R0001 必须 merge_into）。"""
    rules = ts.get("rules", {})
    bad = []
    for code, exp in expected.items():
        actual = rules.get(code, {}).get("load_mode", "")
        if not actual:
            bad.append(f"{code}: 规则不存在或无 load_mode")
        elif actual != exp:
            bad.append(f"{code}: {actual} ≠ {exp}")
    if bad:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"load_mode 契约不符: {bad}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"load_mode 契约匹配 ({len(expected)} 规则)",
        )
    ]


def _check_segmentation(dec: dict, ts: dict) -> list[CheckResult]:
    """segmentation_decision=分段 时 segmentation_reason 必须非空。"""
    ca = dec.get("complexity_analysis", {}) if dec else {}
    if not ca:
        # fallback ts.design.complexity_analysis
        ca = ts.get("design", {}).get("complexity_analysis", {})
    decision = ca.get("segmentation_decision", "")
    if decision != "分段":
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.PASS,
                detail=f"不分段（decision={decision or '未设'}），segmentation 检查不适用",
            )
        ]
    reason = ca.get("segmentation_reason", "")
    if not reason:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail="segmentation=分段 但缺 segmentation_reason",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail="segmentation 自洽（分段+有理由）",
        )
    ]


def _check_field_not_mapped_from(ts: dict, spec: dict) -> list[CheckResult]:
    """字段不能映射自某表（数据源缺口陷阱用）。

    spec 形如 {field: customer_level, not_from_table: dim_customer}：
    遍历所有规则的 fields，若该 field 的 source_fields 里出现了 not_from_table，则 FAIL。
    设计意图：designer 发现数据源缺口后，应拒绝把字段默默映射到诱导表。
    若字段未出现在任何规则的 source_fields 里（降级为 assign/缺口标注），视为 PASS。
    """
    target_field = spec.get("field", "")
    forbidden_table = spec.get("not_from_table", "")
    if not target_field or not forbidden_table:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.SKIP,
                detail="field_not_mapped_from 配置缺 field 或 not_from_table，跳过",
            )
        ]

    rules = ts.get("rules", {})
    violated: list[str] = []
    for code, r in rules.items():
        for f in r.get("fields", []):
            if f.get("target_field") != target_field:
                continue
            for sf in f.get("source_fields", []):
                tbl = sf.get("table", "")
                # 表名可能带 schema（dim.dim_customer）或不带，按裸表名比较
                if tbl.split(".")[-1] == forbidden_table.split(".")[-1]:
                    violated.append(f"{code}/{target_field}→{tbl}")
    if violated:
        return [
            CheckResult(
                check_type="design",
                status=CheckStatus.FAIL,
                detail=f"{target_field} 错误映射自 {forbidden_table}: {violated}",
            )
        ]
    return [
        CheckResult(
            check_type="design",
            status=CheckStatus.PASS,
            detail=f"{target_field} 未映射自 {forbidden_table}（缺口已识别/未用错来源）",
        )
    ]
