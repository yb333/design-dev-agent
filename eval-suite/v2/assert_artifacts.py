"""产物层断言：检查 ts.json 结构 + 产出文件齐全。

硬约束：文件查找用确定性文件名拼接（CLAUDE.md 禁止 glob）。
- DDL: ddl/create_table_{f_table}.sql, ddl/create_view_{i_view}.sql
- 回退: ddl_rollback/rollback_create_table_{f_table}.sql 等
- SELECT: select/{rule_code}_select.sql
- 制品: export/shujia_{table}.xlsx 等
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 复用旧体系的 CheckResult / CheckStatus（validators 作为包加载，不动旧代码）
import sys

_EVAL_SUITE = Path(__file__).resolve().parent.parent
if str(_EVAL_SUITE) not in sys.path:
    sys.path.insert(0, str(_EVAL_SUITE))

from validators.base import CheckResult, CheckStatus  # type: ignore

from checks_schema import DEFAULT_ARTIFACT_CHECKS


def run_artifact_checks(
    output_dir: Path, checks: dict | None = None
) -> list[CheckResult]:
    """跑产物层全部断言。

    Args:
        output_dir: ddlc_design_dev 目录。
        checks: artifacts 段配置（None 用默认）。
    """
    cfg = checks or DEFAULT_ARTIFACT_CHECKS
    results: list[CheckResult] = []

    ts_path = output_dir / "ts.json"
    if not ts_path.exists():
        results.append(
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"ts.json 不存在: {ts_path}",
            )
        )
        return results

    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 1. ts.json 顶层键
    results.extend(_check_top_keys(ts, cfg.get("ts_json_top_keys", [])))

    # 2. audit_fields
    results.extend(_check_audit_fields(ts, cfg))

    # 3. business_key 非空
    results.extend(_check_business_key(ts))

    # 4. 每规则有 load_mode
    if cfg.get("each_rule_has_load_mode", True):
        results.extend(_check_load_mode(ts))

    # 5. 文件齐全（确定性文件名，无 glob）
    results.extend(_check_files(output_dir, ts))

    # 6. DDL/回退成对
    if cfg.get("ddl_rollback_paired", True):
        results.extend(_check_ddl_rollback_paired(output_dir, ts))

    # 7. I 视图无 SELECT *
    if cfg.get("no_select_star_in_view", True):
        results.extend(_check_no_select_star(output_dir, ts))

    return results


# ============================================================
# 各断言实现
# ============================================================


def _check_top_keys(ts: dict, expected_keys: list[str]) -> list[CheckResult]:
    if not expected_keys:
        return []
    actual = set(ts.keys())
    missing = [k for k in expected_keys if k not in actual]
    if missing:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"ts.json 缺顶层键: {missing}",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail=f"ts.json 顶层键齐全 ({len(expected_keys)} 个)",
        )
    ]


def _check_audit_fields(ts: dict, cfg: dict) -> list[CheckResult]:
    expected_names = set(cfg.get("audit_field_names", []))
    expected_count = cfg.get("audit_fields_count", 4)
    audit = ts.get("design", {}).get("audit_fields", {})

    if len(audit) != expected_count:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"audit_fields 数量不对: {len(audit)} (应为 {expected_count})",
            )
        ]

    actual_names = set(audit.keys())
    missing = expected_names - actual_names
    extra = actual_names - expected_names
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"缺 {sorted(missing)}")
        if extra:
            parts.append(f"多 {sorted(extra)}")
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"audit_fields 名称不对: {'; '.join(parts)}",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail=f"audit_fields 正确 ({len(audit)} 个)",
        )
    ]


def _check_business_key(ts: dict) -> list[CheckResult]:
    bk = ts.get("design", {}).get("business_key", [])
    if not bk:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail="design.business_key 为空",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail=f"business_key: {bk}",
        )
    ]


def _check_load_mode(ts: dict) -> list[CheckResult]:
    rules = ts.get("rules", {})
    if not rules:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail="rules 为空",
            )
        ]
    missing = [code for code, r in rules.items() if not r.get("load_mode")]
    if missing:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"规则缺 load_mode: {missing}",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail=f"每规则有 load_mode ({len(rules)} 规则)",
        )
    ]


def _check_files(output_dir: Path, ts: dict) -> list[CheckResult]:
    """文件齐全检查（确定性文件名，无 glob）。"""
    results: list[CheckResult] = []
    missing_files: list[str] = []

    # ts.json / ts.md / design_decisions.yaml
    for rel in ["ts.json", "ts.md", "_internal/design_decisions.yaml"]:
        if not (output_dir / rel).exists():
            missing_files.append(rel)

    # DDL: create_table_{f_table}.sql + create_view_{i_view}.sql
    meta = ts.get("meta", {}).get("target", {})
    f_table = meta.get("f_table", {}).get("table", "")
    i_view = meta.get("i_view", {}).get("table", "")

    if f_table:
        ddl_file = output_dir / "ddl" / f"create_table_{f_table}.sql"
        if not ddl_file.exists():
            missing_files.append(f"ddl/create_table_{f_table}.sql")
    if i_view:
        view_file = output_dir / "ddl" / f"create_view_{i_view}.sql"
        if not view_file.exists():
            missing_files.append(f"ddl/create_view_{i_view}.sql")

    # SELECT: select/{rule_code}_select.sql（每规则）
    for code in ts.get("rules", {}):
        sel_file = output_dir / "select" / f"{code}_select.sql"
        if not sel_file.exists():
            missing_files.append(f"select/{code}_select.sql")

    if missing_files:
        results.append(
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"缺文件 ({len(missing_files)}): {missing_files[:5]}",
            )
        )
    else:
        results.append(
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.PASS,
                detail="产出文件齐全",
            )
        )
    return results


def _check_ddl_rollback_paired(output_dir: Path, ts: dict) -> list[CheckResult]:
    """每个 create_*.sql 应有对应 rollback_create_*.sql（确定性文件名）。"""
    ddl_dir = output_dir / "ddl"
    rb_dir = output_dir / "ddl_rollback"
    if not ddl_dir.exists() or not rb_dir.exists():
        # 没产出 DDL/回退，由文件齐全检查覆盖，这里不重复报
        return []

    meta = ts.get("meta", {}).get("target", {})
    f_table = meta.get("f_table", {}).get("table", "")
    i_view = meta.get("i_view", {}).get("table", "")

    missing_pairs: list[str] = []
    if f_table:
        if (ddl_dir / f"create_table_{f_table}.sql").exists():
            if not (rb_dir / f"rollback_create_table_{f_table}.sql").exists():
                missing_pairs.append(f"rollback_create_table_{f_table}.sql")
    if i_view:
        if (ddl_dir / f"create_view_{i_view}.sql").exists():
            if not (rb_dir / f"rollback_create_view_{i_view}.sql").exists():
                missing_pairs.append(f"rollback_create_view_{i_view}.sql")

    if missing_pairs:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"DDL/回退不成对，缺: {missing_pairs}",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail="DDL/回退成对",
        )
    ]


def _check_no_select_star(output_dir: Path, ts: dict) -> list[CheckResult]:
    """I 视图 DDL 不应含 SELECT *。"""
    meta = ts.get("meta", {}).get("target", {})
    i_view = meta.get("i_view", {}).get("table", "")
    if not i_view:
        return []
    view_file = output_dir / "ddl" / f"create_view_{i_view}.sql"
    if not view_file.exists():
        return []
    content = view_file.read_text(encoding="utf-8")
    # 精确匹配 SELECT * FROM（排除 SELECT 字段列表里的 *）
    if re.search(r"SELECT\s+\*\s+FROM", content, re.IGNORECASE):
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"I 视图 {i_view} 含 SELECT *（应列出全部字段）",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail="I 视图无 SELECT *",
        )
    ]
