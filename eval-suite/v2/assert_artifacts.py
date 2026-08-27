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
from _paths import find_select_file, find_ts_md
from standards import STANDARD_AUDIT_NAMES, standard_audit_type, norm_type
import assert_sql
from golden import parse_ddl_columns


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

    # 8. DDL 自洽（零配置默认）：DDL↔ts 列/类型/分布键 + 视图列 + 回退内容
    results.extend(_check_ddl_consistency(output_dir, ts))

    # 9. 审计字段标准写法（零配置）：类型必须=标准（不看 mapping），缺失=违规
    results.extend(_check_audit_standard(output_dir, ts))

    return results


def _check_audit_standard(output_dir: Path, ts: dict) -> list[CheckResult]:
    """审计字段标准写法断言：ts 字段与 DDL 列里出现的审计字段，类型必须等于标准。

    标准单一来源 dws_standards.py（经 standards.py 接入）。不管 mapping 写没写、
    写的什么类型，审计字段类型固定——mapping 里的写法不做依据。
    """
    results: list[CheckResult] = []
    bad: list[str] = []

    # ts 侧：tables 字段里的审计字段
    for tname, tdef in (ts.get("tables") or {}).items():
        for f in tdef.get("fields", []):
            col = (f.get("target_field") or "").lower()
            std = standard_audit_type(col)
            if not std:
                continue
            got = norm_type(f.get("field_type") or "")
            if got and got != std:
                bad.append(f"ts.{tname}.{col}: {got} ≠ 标准 {std}")

    # DDL 侧：列里的审计字段 + 缺失检查
    ddl_dir = output_dir / "ddl"
    for tname in (ts.get("tables") or {}):
        ddl_file = ddl_dir / f"create_table_{tname}.sql"
        cols = parse_ddl_columns(ddl_file)
        if not cols:
            continue
        present_audit = set(cols) & STANDARD_AUDIT_NAMES
        missing_audit = STANDARD_AUDIT_NAMES - present_audit
        if missing_audit:
            bad.append(f"DDL.{tname} 缺审计字段 {sorted(missing_audit)}")
        for col in present_audit:
            std = standard_audit_type(col)
            got = norm_type(cols[col])
            if got != std:
                bad.append(f"DDL.{tname}.{col}: {got} ≠ 标准 {std}")

    if bad:
        return [
            CheckResult(
                check_type="artifacts",
                status=CheckStatus.FAIL,
                detail=f"审计字段不合标准写法: {bad[:5]}（→ designer/assemble_ddl，"
                       f"标准见 dws_standards.py，不看 mapping 写法）",
            )
        ]
    return [
        CheckResult(
            check_type="artifacts",
            status=CheckStatus.PASS,
            detail="审计字段符合标准写法（4字段类型=标准）",
        )
    ]


# ============================================================
# DDL 自洽断言（生成环节 bug 的探测器，归因精确：不一致=对应生成脚本问题）
# ============================================================


def _norm_type(t: str) -> str:
    """类型归一：小写去空格；返回 (基类型, 精度或空)。"""
    t = (t or "").strip().lower().replace(" ", "")
    base, _, prec = t.partition("(")
    return base, prec.rstrip(")") if prec else ""


def _check_ddl_consistency(output_dir: Path, ts: dict) -> list[CheckResult]:
    results: list[CheckResult] = []
    audit = {k.lower() for k in ts.get("design", {}).get("audit_fields", {})}
    ddl_dir = output_dir / "ddl"

    for tname, tdef in (ts.get("tables") or {}).items():
        ddl_file = ddl_dir / f"create_table_{tname}.sql"
        if not ddl_file.exists():
            continue  # 文件缺失由文件齐全检查负责
        ddl_cols = parse_ddl_columns(ddl_file)

        # 8a. 列集合：DDL ⊇ ts fields；DDL 多出的列必须属于审计字段
        ts_fields = {f.get("target_field", "").lower(): (f.get("field_type") or "")
                     for f in tdef.get("fields", [])}
        missing = set(ts_fields) - set(ddl_cols)
        extra = set(ddl_cols) - set(ts_fields) - audit
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"DDL缺列 {sorted(missing)}")
            if extra:
                parts.append(f"DDL多出非审计列 {sorted(extra)}")
            results.append(CheckResult(
                check_type="artifacts", status=CheckStatus.FAIL,
                detail=f"DDL列≠ts列[{tname}]: {'; '.join(parts)}（→ assemble_ddl）",
            ))
        else:
            results.append(CheckResult(
                check_type="artifacts", status=CheckStatus.PASS,
                detail=f"DDL列自洽[{tname}] ({len(ddl_cols)}列)",
            ))

        # 8b. 类型一致：基类型必须相等；双方都有精度时精度也须相等
        bad_types = []
        for col, ts_type in ts_fields.items():
            ddl_type = ddl_cols.get(col, "")
            if not ddl_type:
                continue
            b1, p1 = _norm_type(ts_type)
            b2, p2 = _norm_type(ddl_type)
            if b1 != b2 or (p1 and p2 and p1 != p2):
                bad_types.append(f"{col}: ts={ts_type} ddl={ddl_type}")
        if bad_types:
            results.append(CheckResult(
                check_type="artifacts", status=CheckStatus.FAIL,
                detail=f"DDL类型≠ts类型[{tname}]: {bad_types[:4]}（→ assemble_ddl）",
            ))

        # 8c. 分布键：ts 声明了 distribution_key → DDL 必须真有 DISTRIBUTE BY 且含键列
        dist_keys = [k.lower() for k in (tdef.get("distribution_key") or [])]
        if dist_keys:
            content = ddl_file.read_text(encoding="utf-8").lower()
            if "distribute by" not in content:
                results.append(CheckResult(
                    check_type="artifacts", status=CheckStatus.FAIL,
                    detail=f"DDL缺DISTRIBUTE BY[{tname}]（ts声明分布键{dist_keys}）（→ assemble_ddl）",
                ))
            else:
                absent = [k for k in dist_keys if k not in content]
                if absent:
                    results.append(CheckResult(
                        check_type="artifacts", status=CheckStatus.FAIL,
                        detail=f"DDL分布键缺列[{tname}]: {absent}（→ assemble_ddl）",
                    ))

    # 8d. I 视图列 == F 表 DDL 列
    meta = ts.get("meta", {}).get("target", {})
    i_view = meta.get("i_view", {}).get("table", "")
    f_table = meta.get("f_table", {}).get("table", "")
    view_file = output_dir / "ddl" / f"create_view_{i_view}.sql" if i_view else None
    f_ddl = output_dir / "ddl" / f"create_table_{f_table}.sql" if f_table else None
    if view_file and view_file.exists() and f_ddl and f_ddl.exists():
        view_sql = view_file.read_text(encoding="utf-8")
        view_cols = {c.lower() for c in assert_sql._extract_select_columns(view_sql)}
        f_cols = set(parse_ddl_columns(f_ddl))
        if not view_cols and len(view_sql) > 50:
            # 提取空集但视图SQL非空——解析失败不是真差异，别误报
            results.append(CheckResult(
                check_type="artifacts", status=CheckStatus.FAIL,
                detail=f"I视图列提取失败[{i_view}]（视图SQL解析异常，非差异；"
                       f"请把视图SQL发维护者看解析兼容性）",
            ))
        else:
            miss = f_cols - view_cols
            if miss:
                results.append(CheckResult(
                    check_type="artifacts", status=CheckStatus.FAIL,
                    detail=f"I视图列缺F表列[{i_view}]: 缺{sorted(miss)[:5]} | "
                           f"F表共{len(f_cols)}列 视图提取到{sorted(view_cols)[:5]}…"
                           f"（→ assemble_ddl 或视图SQL解析差异）",
                ))

    # 8e. 回退 SQL 必须含 DROP（成对性已有检查，这里查内容）
    rb_dir = output_dir / "ddl_rollback"
    if rb_dir.exists():
        no_drop = [f.name for f in sorted(rb_dir.iterdir())
                   if f.suffix == ".sql" and "drop" not in f.read_text(encoding="utf-8").lower()]
        if no_drop:
            results.append(CheckResult(
                check_type="artifacts", status=CheckStatus.FAIL,
                detail=f"回退SQL缺DROP语句: {no_drop[:4]}（→ assemble_ddl）",
            ))

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

    # ts.json / design_decisions.yaml（固定路径）
    for rel in ["ts.json", "_internal/design_decisions.yaml"]:
        if not (output_dir / rel).exists():
            missing_files.append(rel)
    # ts.md（兼容 ts.md 和 {资产}_ts.md 两种命名）
    if not find_ts_md(output_dir):
        missing_files.append("ts.md")

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

    # SELECT: 每规则的取数 SQL（兼容 etl/{code}.sql 和 select/{code}_select.sql）
    for code in ts.get("rules", {}):
        if not find_select_file(output_dir, code):
            missing_files.append(f"SELECT for {code} (etl/{code}.sql 或 select/{code}_select.sql)")

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
