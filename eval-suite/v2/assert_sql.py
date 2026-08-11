"""code 质量断言：检查 coder 的 SELECT SQL。

基于 SQL AST 语义检查（不比字符串），复用 validators/content.py 的 _extract_* 函数。
断言来自 checks.yaml 的 code 段（按规则配置）。

断言类型：
- fields_required：SELECT 字段 ⊇ 期望字段（集合包含）
- join_tables：JOIN 表集合 == 期望（集合相等）
- where_must_contain：WHERE 含特定过滤（如 del_flag）
- group_by_granularity：GROUP BY 列 == 期望粒度
- case_when_must_have_else：所有 CASE 有 ELSE
- no_select_star：禁 SELECT *
- audit_fields_in_select：审计字段齐全
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 复用 base.py + content.py（validators 作为包加载，content 依赖相对 import）
_EVAL_SUITE = Path(__file__).resolve().parent.parent
if str(_EVAL_SUITE) not in sys.path:
    sys.path.insert(0, str(_EVAL_SUITE))

from validators.base import CheckResult, CheckStatus  # type: ignore

# 复用 content.py 的 _extract_* 函数（模块级纯函数）
from validators.content import (  # type: ignore
    _extract_case_whens,
    _extract_del_flag_filters,
    _extract_join_tables,
)

from _paths import find_select_file, list_select_rules


def _extract_groupby_columns(sql_text: str) -> set[str]:
    """提取 GROUP BY 列名（兼容裸 SELECT 和 INSERT...SELECT）。

    content.py 原版只处理 INSERT...SELECT，裸 SELECT 提取不到。
    这里兼容两种：找所有 Select 节点的 group 子句。
    """
    import sqlglot
    from sqlglot import exp

    cols: set[str] = set()
    try:
        trees = sqlglot.parse(sql_text, dialect="postgres")
        for tree in trees:
            if not tree:
                continue
            for select in tree.find_all(exp.Select):
                group = select.args.get("group")
                if group:
                    for expr in group.expressions:
                        if isinstance(expr, exp.Column):
                            cols.add(expr.name.lower())
    except Exception:
        pass
    return cols

# 标准审计字段
AUDIT_FIELDS = {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"}


def run_code_checks(
    output_dir: Path,
    checks: dict | None,
    ts: dict | None = None,
) -> list[CheckResult]:
    """跑 code 质量断言。

    Args:
        output_dir: ddlc_design_dev 目录。
        checks: checks.yaml 的 code 段（按规则）。
        ts: ts.json（用来取规则列表 + 审计字段）。
    """
    cfg = checks or {}
    results: list[CheckResult] = []

    # 确定要检查的规则：checks.yaml.code > ts.json.rules > 扫描产出（etl/select 合并）
    if cfg:
        rule_codes = list(cfg.keys())
    elif ts:
        rule_codes = list(ts.get("rules", {}).keys())
    else:
        rule_codes = list_select_rules(output_dir)

    if not rule_codes:
        return [
            CheckResult(
                check_type="code",
                status=CheckStatus.SKIP,
                detail="无规则可检查（未配置 code 断言且产出无 SELECT）",
            )
        ]

    for code in rule_codes:
        # 兼容 new-pipe etl/{code}.sql 和老格式 select/{code}_select.sql
        select_file = find_select_file(output_dir, code)
        if not select_file:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{code}: SELECT 文件不存在 (etl/{code}.sql 和 select/{code}_select.sql 都没有)",
                )
            )
            continue

        sql_text = select_file.read_text(encoding="utf-8")
        rule_cfg = cfg.get(code, {}) if cfg else {}
        results.extend(_check_one_rule(code, sql_text, rule_cfg))

    return results


def _check_one_rule(code: str, sql_text: str, rule_cfg: dict) -> list[CheckResult]:
    """对单个规则的 SELECT 跑全部配置的断言。"""
    results: list[CheckResult] = []
    # 前缀统一加 rule_code，方便归因定位
    pfx = f"{code}: "

    # 1. 字段完整率（集合包含）
    if "fields_required" in rule_cfg:
        required = set(rule_cfg["fields_required"])
        actual = _extract_select_columns(sql_text)
        missing = required - actual
        if missing:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}字段缺失: {sorted(missing)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.PASS,
                    detail=f"{pfx}字段完整 ({len(required)}/{len(required)})",
                )
            )

    # 2. JOIN 表覆盖（集合相等）
    if "join_tables" in rule_cfg:
        expected_bare = {t.split(".")[-1] for t in rule_cfg["join_tables"]}
        actual_tables = _extract_join_tables(sql_text)
        actual_bare = {t.split(".")[-1] for t in actual_tables}
        missing = expected_bare - actual_bare
        if missing:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}JOIN 表缺失: {sorted(missing)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.PASS,
                    detail=f"{pfx}JOIN 表覆盖完整",
                )
            )

    # 3. del_flag 过滤（默认开）
    if rule_cfg.get("where_must_contain_del_flag", True):
        aliases = _extract_del_flag_filters(sql_text)
        unfiltered = {a for a, ok in aliases.items() if not ok}
        if unfiltered:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}del_flag 未过滤的表: {sorted(unfiltered)}",
                )
            )
        elif aliases:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.PASS,
                    detail=f"{pfx}del_flag 过滤完整 ({len(aliases)} 表)",
                )
            )

    # 4. GROUP BY 粒度
    if "group_by_granularity" in rule_cfg:
        expected = set(rule_cfg["group_by_granularity"])
        actual = _extract_groupby_columns(sql_text)
        missing = expected - actual
        if missing:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}GROUP BY 缺列: {sorted(missing)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.PASS,
                    detail=f"{pfx}GROUP BY 粒度正确 ({len(expected)} 列)",
                )
            )

    # 5. CASE WHEN 有 ELSE（默认开）
    if rule_cfg.get("case_when_must_have_else", True):
        cases = _extract_case_whens(sql_text)
        no_else = [c["condition"][:40] for c in cases if not c["has_else"]]
        if no_else:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}CASE 缺 ELSE ({len(no_else)}): {no_else[:2]}",
                )
            )
        elif cases:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.PASS,
                    detail=f"{pfx}CASE WHEN 都有 ELSE ({len(cases)})",
                )
            )

    # 6. 无 SELECT *（默认开）
    if rule_cfg.get("no_select_star", True):
        if re.search(r"SELECT\s+\*\s+FROM", sql_text, re.IGNORECASE):
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}含 SELECT *（应列出全部字段）",
                )
            )

    # 7. 审计字段齐全（默认开）
    if rule_cfg.get("audit_fields_in_select", True):
        actual = _extract_select_columns(sql_text)
        missing_audit = AUDIT_FIELDS - actual
        if missing_audit:
            results.append(
                CheckResult(
                    check_type="code",
                    status=CheckStatus.FAIL,
                    detail=f"{pfx}审计字段缺失: {sorted(missing_audit)}",
                )
            )

    # 没配任何断言且没默认报错，给个占位 pass
    if not results:
        results.append(
            CheckResult(
                check_type="code",
                status=CheckStatus.PASS,
                detail=f"{pfx}SELECT 检查通过（无配置项触发）",
            )
        )

    return results


def _extract_select_columns(sql_text: str) -> set[str]:
    """提取 SELECT 的输出列名（bare name，去掉别名前缀）。

    复用 sqlglot 解析，比正则稳。
    """
    import sqlglot
    from sqlglot import exp

    cols: set[str] = set()
    try:
        trees = sqlglot.parse(sql_text, dialect="postgres")
        for tree in trees:
            if not tree:
                continue
            for select in tree.find_all(exp.Select):
                for proj in select.expressions:
                    # alias 优先取别名，否则取列名
                    if isinstance(proj, exp.Alias):
                        cols.add(proj.alias.lower())
                    elif isinstance(proj, exp.Column):
                        cols.add(proj.name.lower())
                    else:
                        # 表达式（SUM/CASE 等）取 alias，无 alias 取文本
                        alias = getattr(proj, "alias", "")
                        if alias:
                            cols.add(alias.lower())
    except Exception:
        pass
    return cols
