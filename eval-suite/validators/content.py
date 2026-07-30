"""Content validator — field completeness, ETL logic coverage, safety compliance.

All comparisons are driven by golden data (mapping.json, design.md, ETL SQL),
never hardcoded for a specific case.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

from .base import BaseValidator, CheckResult, CheckStatus
from .sql import _strip_dws_clauses, _strip_etl_clauses, _clean_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_mapping_fields(golden_dir: Path) -> set[str]:
    """Extract target field names from golden mapping.json."""
    mapping_path = golden_dir / "01_input" / "mapping.json"
    if not mapping_path.exists():
        return set()
    with open(mapping_path, encoding="utf-8") as f:
        data = json.load(f)
    return {m["target_column"] for m in data.get("field_mappings", []) if "target_column" in m}


def _load_source_tables(golden_dir: Path) -> list[dict[str, str]]:
    """Extract source table info from golden mapping.json."""
    mapping_path = golden_dir / "01_input" / "mapping.json"
    if not mapping_path.exists():
        return []
    with open(mapping_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("source_tables", [])


def _extract_ddl_columns(output_dir: Path) -> set[str]:
    """Extract column names from actual DDL files."""
    columns: set[str] = set()
    ddl_dir = output_dir / "04_ddl"
    if not ddl_dir.exists():
        return columns
    for sql_file in ddl_dir.glob("create_table_*.sql"):
        content = sql_file.read_text(encoding="utf-8")
        clean = _strip_dws_clauses(content)
        try:
            tree = sqlglot.parse_one(clean, dialect="postgres")
            if isinstance(tree, exp.Create):
                for col in tree.find_all(exp.ColumnDef):
                    columns.add(_clean_name(col.name))
        except Exception:
            pass
    return columns


def _extract_join_tables(etl_sql: str) -> list[str]:
    """Extract table names from all FROM/JOIN clauses in ETL SQL."""
    tables: list[str] = []
    try:
        clean = _strip_etl_clauses(etl_sql)
        trees = sqlglot.parse(clean, dialect="postgres")
        for tree in trees:
            if not tree:
                continue
            for table in tree.find_all(exp.Table):  # type: ignore[union-attr]
                name = ".".join(_clean_name(p.name) for p in table.parts)
                if name and name not in tables:
                    tables.append(name)
    except Exception:
        pass
    return tables


def _extract_groupby_columns(etl_sql: str) -> set[str]:
    """Extract GROUP BY column names from ETL SQL."""
    columns: set[str] = set()
    try:
        trees = sqlglot.parse(etl_sql, dialect="postgres")
        for tree in trees:
            if not isinstance(tree, exp.Insert):
                continue
            select = tree.find(exp.Select)
            if select and select.args.get("group"):
                for expr in select.args["group"].expressions:
                    if isinstance(expr, exp.Column):
                        columns.add(_clean_name(expr.name))
    except Exception:
        pass
    return columns


def _extract_rpt_codes(etl_sql: str) -> set[str]:
    """Extract rpt_code (or similar coded) values from CASE WHEN in ETL SQL."""
    codes: set[str] = set()
    for m in re.finditer(r"rpt_code\s*=\s*'([^']+)'", etl_sql, re.IGNORECASE):
        codes.add(m.group(1))
    return codes


def _extract_case_whens(etl_sql: str) -> list[dict[str, object]]:
    """Extract CASE WHEN blocks: condition and whether ELSE exists."""
    cases: list[dict[str, object]] = []
    pattern = re.compile(
        r"CASE\s+(.*?)\s*END", re.IGNORECASE | re.DOTALL
    )
    for m in pattern.finditer(etl_sql):
        body = m.group(1)
        has_else = bool(re.search(r"\bELSE\b", body, re.IGNORECASE))
        when_conds = re.findall(
            r"WHEN\s+(.*?)\s+THEN", body, re.IGNORECASE
        )
        cond_summary = "; ".join(
            re.sub(r"\s+", " ", w.strip())[:80] for w in when_conds
        )
        cases.append({
            "condition": cond_summary,
            "has_else": has_else,
        })
    return cases


_CTE_NAME_PATTERN = re.compile(
    r"\b(\w+)\s+AS\s*\(",
    re.IGNORECASE,
)

_SQL_KEYWORDS = frozenset({
    "on", "and", "where", "set", "select", "as", "into",
    "from", "join", "left", "right", "inner", "outer",
    "group", "order", "having", "limit", "union", "all",
    "not", "null", "exists", "in", "between", "like",
    "case", "when", "then", "else", "end", "is", "or",
    "by", "desc", "asc", "distinct", "create", "drop",
    "insert", "update", "delete", "truncate", "alter",
    "values", "with", "for", "if", "to",
})


def _extract_cte_names(etl_sql: str) -> set[str]:
    with_pos = re.search(r"\bWITH\b", etl_sql, re.IGNORECASE)
    if not with_pos:
        return set()
    insert_pos = etl_sql.upper().find("INSERT INTO")
    if insert_pos < 0:
        insert_pos = len(etl_sql)
    cte_region = etl_sql[with_pos.end():insert_pos]
    return {m.group(1).lower() for m in _CTE_NAME_PATTERN.finditer(cte_region)}


def _extract_del_flag_filters(etl_sql: str) -> dict[str, bool]:
    cte_names = _extract_cte_names(etl_sql)

    main_query = etl_sql
    insert_pos = etl_sql.upper().find("INSERT INTO")
    if insert_pos > 0:
        main_query = etl_sql[insert_pos:]

    aliases: dict[str, bool] = {}
    join_pattern = re.compile(
        r"(?:LEFT\s+JOIN|INNER\s+JOIN|JOIN)\s+"
        r"(?:[\w.]+\.)?(\w+)\s+(?:AS\s+)?(\w+)",
        re.IGNORECASE,
    )
    for m in join_pattern.finditer(main_query):
        table_name = m.group(1).lower()
        alias = m.group(2).lower()
        if alias in _SQL_KEYWORDS:
            continue
        if not alias[0].isalpha():
            continue
        if table_name in cte_names:
            continue
        if alias not in aliases:
            aliases[alias] = False

    for alias in aliases:
        if re.search(
            rf"\b{alias}\.del_flag\b", etl_sql, re.IGNORECASE,
        ):
            aliases[alias] = True
    return aliases


class ContentValidator(BaseValidator):
    """Validate content-level correctness: field completeness, ETL logic, safety."""

    @property
    def name(self) -> str:
        return "content"

    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]:
        check_type = check_config.get("type", "")

        if check_type == "field_completeness":
            return self._check_field_completeness(output_dir, golden_dir)
        if check_type == "etl_logic":
            return self._check_etl_logic(output_dir, golden_dir)
        if check_type == "safety":
            return self._check_safety(output_dir, golden_dir)

        return [
            CheckResult(
                check_type=check_type,
                status=CheckStatus.SKIP,
                detail=f"Unknown check type: {check_type}",
            )
        ]

    # ------------------------------------------------------------------
    # field_completeness
    # ------------------------------------------------------------------
    def _check_field_completeness(
        self, output_dir: Path, golden_dir: Path | None
    ) -> list[CheckResult]:
        if not golden_dir:
            return [CheckResult(
                check_type="field_completeness",
                status=CheckStatus.SKIP,
                detail="No golden_dir configured",
            )]

        golden_fields = _load_mapping_fields(golden_dir)
        if not golden_fields:
            return [CheckResult(
                check_type="field_completeness",
                status=CheckStatus.SKIP,
                detail="No field_mappings in golden mapping.json",
            )]

        actual_fields = _extract_ddl_columns(output_dir)

        matched = golden_fields & actual_fields
        missing = golden_fields - actual_fields
        extra = actual_fields - golden_fields
        hit_rate = len(matched) / len(golden_fields) if golden_fields else 0

        evidence_lines = [
            f"Golden fields: {sorted(golden_fields)}",
            f"Actual fields: {sorted(actual_fields)}",
        ]
        if missing:
            evidence_lines.append(f"Missing in actual: {sorted(missing)}")
        if extra:
            evidence_lines.append(f"Extra in actual: {sorted(extra)}")

        status = CheckStatus.PASS if hit_rate >= 1.0 else (
            CheckStatus.FAIL if hit_rate < 0.5 else CheckStatus.PASS
        )
        score = round(hit_rate * 100, 1)

        return [CheckResult(
            check_type="field_completeness",
            status=status,
            detail=(
                f"Field hit rate: {len(matched)}/{len(golden_fields)} "
                f"({score}%)"
            ),
            evidence="\n".join(evidence_lines),
            score=score,
        )]

    # ------------------------------------------------------------------
    # etl_logic
    # ------------------------------------------------------------------
    def _check_etl_logic(
        self, output_dir: Path, golden_dir: Path | None
    ) -> list[CheckResult]:
        results: list[CheckResult] = []

        etl_dir = output_dir / "05_etl"
        if not etl_dir.exists():
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.SKIP,
                detail="05_etl directory not found",
            )]

        etl_files = sorted(etl_dir.glob("*.sql"))
        if not etl_files:
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.SKIP,
                detail="No ETL SQL files found",
            )]

        etl_sql = "\n".join(
            f.read_text(encoding="utf-8") for f in etl_files
        )

        # --- 1. JOIN table coverage ---
        if golden_dir:
            results.extend(
                self._check_join_coverage(etl_sql, golden_dir)
            )
        else:
            results.append(CheckResult(
                check_type="etl_logic",
                status=CheckStatus.SKIP,
                detail="JOIN coverage: no golden_dir",
            ))

        # --- 2. CASE WHEN rpt_code coverage ---
        results.extend(self._check_rpt_code_coverage(etl_sql, golden_dir))

        # --- 3. GROUP BY granularity ---
        results.extend(self._check_group_by(etl_sql, golden_dir))

        return results

    def _check_join_coverage(
        self, etl_sql: str, golden_dir: Path
    ) -> list[CheckResult]:
        source_tables = _load_source_tables(golden_dir)
        expected_tables: set[str] = set()
        for st in source_tables:
            schema = st.get("source_schema", "")
            table = st.get("source_table", "")
            if schema and table:
                expected_tables.add(f"{schema}.{table}")

        actual_tables = _extract_join_tables(etl_sql)
        actual_bare = {
            t.split(".")[-1] for t in actual_tables
        }
        expected_bare = {
            t.split(".")[-1] for t in expected_tables
        }

        matched_bare = expected_bare & actual_bare
        missing_bare = expected_bare - actual_bare

        evidence_lines: list[str] = []
        if missing_bare:
            evidence_lines.append(f"Missing JOIN tables: {sorted(missing_bare)}")

        hit_rate = (
            len(matched_bare) / len(expected_bare) if expected_bare else 1.0
        )
        status = (
            CheckStatus.PASS if hit_rate >= 1.0
            else CheckStatus.FAIL
        )

        return [CheckResult(
            check_type="etl_logic",
            status=status,
            detail=(
                f"JOIN table coverage: {len(matched_bare)}/{len(expected_bare)} "
                f"({round(hit_rate * 100, 1)}%)"
            ),
            evidence="\n".join(evidence_lines) if evidence_lines else "",
            score=round(hit_rate * 100, 1),
        )]

    def _check_rpt_code_coverage(
        self, etl_sql: str, golden_dir: Path | None
    ) -> list[CheckResult]:
        actual_codes = _extract_rpt_codes(etl_sql)

        golden_codes: set[str] = set()
        if golden_dir:
            for sql_file in (golden_dir / "05_etl").glob("*.sql"):
                golden_codes |= _extract_rpt_codes(
                    sql_file.read_text(encoding="utf-8")
                )

        if not golden_codes:
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.PASS,
                detail="No rpt_code pattern detected (not applicable for this case)",
                score=100.0,
            )]

        matched = golden_codes & actual_codes
        missing = golden_codes - actual_codes
        hit_rate = len(matched) / len(golden_codes)

        evidence_lines: list[str] = []
        if missing:
            evidence_lines.append(f"Missing rpt_codes: {sorted(missing)}")
            evidence_lines.append(
                f"Covered: {sorted(matched)}, Expected: {sorted(golden_codes)}"
            )

        return [CheckResult(
            check_type="etl_logic",
            status=CheckStatus.PASS if hit_rate >= 1.0 else CheckStatus.FAIL,
            detail=(
                f"CASE WHEN rpt_code coverage: {len(matched)}/{len(golden_codes)} "
                f"({round(hit_rate * 100, 1)}%)"
            ),
            evidence="\n".join(evidence_lines) if evidence_lines else "",
            score=round(hit_rate * 100, 1),
        )]

    def _check_group_by(
        self, etl_sql: str, golden_dir: Path | None
    ) -> list[CheckResult]:
        gb_cols = _extract_groupby_columns(etl_sql)

        if not golden_dir:
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.SKIP,
                detail="GROUP BY: no golden_dir",
            )]

        mapping_path = golden_dir / "01_input" / "mapping.json"
        if not mapping_path.exists():
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.SKIP,
                detail="GROUP BY: no golden mapping.json",
            )]

        with open(mapping_path, encoding="utf-8") as f:
            data = json.load(f)

        granularity_cols: set[str] = set()
        overview = data.get("overview", {})
        granularity_str = overview.get("target_granularity", "")
        if granularity_str:
            granularity_cols = {
                c.strip().strip('"')
                for c in re.split(r"[,+，\s]+", granularity_str)
                if c.strip()
            }

        if not granularity_cols:
            return [CheckResult(
                check_type="etl_logic",
                status=CheckStatus.PASS,
                detail="GROUP BY: no granularity defined in mapping, skip",
                score=100.0,
            )]

        covered = granularity_cols & gb_cols
        missing = granularity_cols - gb_cols

        return [CheckResult(
            check_type="etl_logic",
            status=CheckStatus.PASS if not missing else CheckStatus.FAIL,
            detail=(
                f"GROUP BY granularity: {len(covered)}/{len(granularity_cols)} "
                f"target cols covered"
                + (f", missing: {sorted(missing)}" if missing else "")
            ),
            score=round(len(covered) / len(granularity_cols) * 100, 1) if granularity_cols else 100.0,
        )]

    # ------------------------------------------------------------------
    # safety
    # ------------------------------------------------------------------
    def _check_safety(
        self, output_dir: Path, golden_dir: Path | None
    ) -> list[CheckResult]:
        results: list[CheckResult] = []

        etl_dir = output_dir / "05_etl"
        if not etl_dir.exists():
            return [CheckResult(
                check_type="safety",
                status=CheckStatus.SKIP,
                detail="05_etl directory not found",
            )]

        etl_files = sorted(etl_dir.glob("*.sql"))
        if not etl_files:
            return [CheckResult(
                check_type="safety",
                status=CheckStatus.SKIP,
                detail="No ETL SQL files found",
            )]

        etl_sql = "\n".join(
            f.read_text(encoding="utf-8") for f in etl_files
        )

        results.extend(self._check_del_flag(etl_sql))
        results.extend(self._check_case_else(etl_sql))

        return results

    def _check_del_flag(self, etl_sql: str) -> list[CheckResult]:
        aliases = _extract_del_flag_filters(etl_sql)
        if not aliases:
            return [CheckResult(
                check_type="safety",
                status=CheckStatus.PASS,
                detail="del_flag: no table aliases to check",
                score=100.0,
            )]

        filtered = {a for a, ok in aliases.items() if ok}
        unfiltered = {a for a, ok in aliases.items() if not ok}
        hit_rate = len(filtered) / len(aliases)

        evidence_lines: list[str] = []
        if unfiltered:
            evidence_lines.append(
                f"Aliases without del_flag: {sorted(unfiltered)}"
            )
            evidence_lines.append(
                f"Aliases with del_flag: {sorted(filtered)}"
            )

        return [CheckResult(
            check_type="safety",
            status=CheckStatus.PASS if not unfiltered else CheckStatus.FAIL,
            detail=(
                f"del_flag filtering: {len(filtered)}/{len(aliases)} "
                f"tables filtered"
                + (f", missing: {sorted(unfiltered)}" if unfiltered else "")
            ),
            evidence="\n".join(evidence_lines) if evidence_lines else "",
            score=round(hit_rate * 100, 1),
        )]

    def _check_case_else(self, etl_sql: str) -> list[CheckResult]:
        cases = _extract_case_whens(etl_sql)
        if not cases:
            return [CheckResult(
                check_type="safety",
                status=CheckStatus.PASS,
                detail="CASE WHEN ELSE: no CASE blocks found",
                score=100.0,
            )]

        with_else = sum(1 for c in cases if c["has_else"])
        without_else = [
            c["condition"] for c in cases if not c["has_else"]
        ]
        hit_rate = with_else / len(cases)

        evidence_lines: list[str] = []
        if without_else:
            evidence_lines.append(
                f"CASE blocks missing ELSE ({len(without_else)}):"
            )
            for cond in without_else[:5]:
                evidence_lines.append(f"  - {cond}")

        return [CheckResult(
            check_type="safety",
            status=CheckStatus.PASS if not without_else else CheckStatus.FAIL,
            detail=(
                f"CASE WHEN ELSE: {with_else}/{len(cases)} "
                f"have ELSE clause"
            ),
            evidence="\n".join(evidence_lines) if evidence_lines else "",
            score=round(hit_rate * 100, 1),
        )]
