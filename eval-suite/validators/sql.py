"""SQL validator — extract SQL structure using sqlglot and compare."""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot
from sqlglot import exp

_INLINE_COMMENT_RE = re.compile(r"/\*.*?\*/")


def _clean_name(name: str) -> str:
    stripped = _INLINE_COMMENT_RE.sub("", name).strip().strip('"')
    return stripped

from .base import BaseValidator, CheckResult, CheckStatus

# sqlglot doesn't recognize DISTRIBUTED BY / TO GROUP natively, so we strip before parsing
# DISTRIBUTE BY HASH(col) or DISTRIBUTED BY (col1, col2)
_DIST_BY_PATTERN = re.compile(
    r"\bDISTRIBUTE[D]?\s+BY\s+(?:HASH\s*)?\(([^)]+)\)", re.IGNORECASE
)
# TO GROUP "LC_DW1" or TO GROUP LC_DW1
_TO_GROUP_PATTERN = re.compile(
    r"\bTO\s+GROUP\s+(\S+)", re.IGNORECASE
)


def _normalize_type(raw: str) -> str:
    """Normalize SQL type to lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", raw.strip().lower())


def _join_table_parts(table_expr: exp.Table) -> str:
    """Join table parts (schema, name) into dotted string, stripping quotes."""
    parts = []
    for part in table_expr.parts:
        parts.append(_clean_name(part.name))
    return ".".join(parts)


# WITH (ORIENTATION = COLUMN, COMPRESSION = LOW)
_WITH_PARAMS_PATTERN = re.compile(
    r"\)\s*WITH\s*\([^)]*\]", re.IGNORECASE
)


def _extract_first_statement(sql: str) -> str:
    """Extract only the first SQL statement (before COMMENT ON or other statements)."""
    first_semicolon = sql.find(";")
    if first_semicolon < 0:
        return sql
    return sql[:first_semicolon + 1]


def _extract_last_statement(sql: str) -> str:
    """Extract the last SQL statement (handles TRUNCATE + INSERT patterns in ETL)."""
    last_semicolon = sql.rfind(";")
    if last_semicolon < 0:
        return sql
    prev_semicolon = sql.rfind(";", 0, last_semicolon)
    if prev_semicolon < 0:
        return sql[last_semicolon:]
    return sql[prev_semicolon + 1:]


_TRUNCATE_PREFIX = re.compile(
    r"^[\s\S]*?TRUNCATE\s+TABLE\s+\S+\s*;\s*", re.IGNORECASE
)


def _strip_dws_clauses(sql: str) -> str:
    """Remove DWS-specific clauses that sqlglot can't parse."""
    sql = _extract_first_statement(sql)
    sql = _DIST_BY_PATTERN.sub("", sql)
    sql = _TO_GROUP_PATTERN.sub("", sql)
    sql = _WITH_PARAMS_PATTERN.sub(")", sql)
    return sql


def _strip_etl_clauses(sql: str) -> str:
    """Remove DWS-specific and TRUNCATE prefix from ETL SQL."""
    sql = _extract_last_statement(sql)
    sql = _DIST_BY_PATTERN.sub("", sql)
    sql = _TO_GROUP_PATTERN.sub("", sql)
    sql = _TRUNCATE_PREFIX.sub("", sql, count=1)
    return sql


def _extract_dist_by(sql: str) -> list[str]:
    """Extract DISTRIBUTED BY column names."""
    m = _DIST_BY_PATTERN.search(sql)
    if not m:
        return []
    return [c.strip().strip('"') for c in m.group(1).split(",")]


def _extract_to_group(sql: str) -> str | None:
    """Extract TO GROUP value."""
    m = _TO_GROUP_PATTERN.search(sql)
    return m.group(1).strip().strip('"') if m else None


def parse_ddl(sql_text: str) -> dict | None:
    """Parse a DDL statement and extract structure.

    Returns dict with keys: table, columns, distributed_by, to_group.
    Returns None if parsing fails.
    """
    distributed_by = _extract_dist_by(sql_text)
    to_group = _extract_to_group(sql_text)
    clean_sql = _strip_dws_clauses(sql_text)

    try:
        tree = sqlglot.parse_one(clean_sql, dialect="postgres")
    except sqlglot.ParseError:
        return None

    if not isinstance(tree, exp.Create):
        return None

    table_expr = tree.find(exp.Table)
    if not table_expr:
        return None

    # Build schema.table from parts to avoid identify=True quote artifacts
    table_parts = []
    for part in table_expr.parts:
        table_parts.append(_clean_name(part.name))
    table_name = ".".join(table_parts)

    columns: dict[str, str] = {}
    for col_def in tree.find_all(exp.ColumnDef):
        col_name = _clean_name(col_def.this.sql(dialect="postgres"))
        col_type = _normalize_type(col_def.args["kind"].sql(dialect="postgres"))
        columns[col_name] = col_type

    return {
        "table": table_name,
        "columns": columns,
        "distributed_by": distributed_by,
        "to_group": to_group,
    }


def parse_etl(sql_text: str) -> dict | None:
    """Parse an ETL statement and extract structure.

    Returns dict with keys: target_table, insert_columns, select_columns,
    from_tables, field_mapping.
    Returns None if parsing fails.
    """
    clean_sql = _strip_etl_clauses(sql_text)

    try:
        tree = sqlglot.parse_one(clean_sql, dialect="postgres")
    except sqlglot.ParseError:
        return None

    if not isinstance(tree, exp.Insert):
        return None

    target_expr = tree.find(exp.Table)
    target_table = ""
    if target_expr:
        target_table = _join_table_parts(target_expr)

    insert_columns: list[str] = []
    insert_part = tree.find(exp.Insert)
    if insert_part:
        schema_node = insert_part.find(exp.Schema)
        if schema_node:
            insert_columns = [
                _clean_name(col.alias_or_name) for col in schema_node.expressions
            ]

    select_expr = tree.find(exp.Select)
    select_columns: list[str] = []
    from_tables: list[str] = []

    if select_expr:
        # Extract SELECT column expressions (aliases preferred)
        for col in select_expr.find_all(exp.Column):
            alias = col.alias
            if alias:
                select_columns.append(_clean_name(alias))
            else:
                select_columns.append(_clean_name(col.sql(dialect="postgres")))

        for table in select_expr.find_all(exp.Table):
            name = _join_table_parts(table)
            if name and name not in from_tables:
                from_tables.append(name)

    # Build field mapping: SELECT alias → INSERT column
    field_mapping: dict[str, str] = {}
    if select_expr and insert_part:
        schema_node = insert_part.find(exp.Schema)
        insert_cols = (
            [_clean_name(col.alias_or_name) for col in schema_node.expressions]
            if schema_node
            else []
        )
        # Extract aliased columns from SELECT in order
        select_aliases: list[str] = []
        for projection in select_expr.find_all(exp.Alias):
            select_aliases.append(_clean_name(projection.alias))
        for i, ic in enumerate(insert_cols):
            if i < len(select_aliases):
                field_mapping[select_aliases[i]] = ic

    return {
        "target_table": target_table,
        "insert_columns": insert_columns,
        "select_columns": select_columns,
        "from_tables": from_tables,
        "field_mapping": field_mapping,
    }


def _load_sql_files(directory: Path, pattern: str) -> list[tuple[str, Path, str]]:
    """Load SQL files from directory. Returns list of (filename, path, content)."""
    files: list[tuple[str, Path, str]] = []
    if not directory.exists():
        return files

    for sql_file in sorted(directory.glob(pattern)):
        if sql_file.is_file() and sql_file.suffix.lower() == ".sql":
            content = sql_file.read_text(encoding="utf-8")
            files.append((sql_file.name, sql_file, content))
    return files


def _compare_column_dicts(
    actual: dict[str, str], golden: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Compare two column name→type dicts. Returns (matched, missing, extra)."""
    actual_norm = {k: _normalize_type(v) for k, v in actual.items()}
    golden_norm = {k: _normalize_type(v) for k, v in golden.items()}

    matched = sorted(set(actual_norm) & set(golden_norm))
    missing = sorted(set(golden_norm) - set(actual_norm))
    extra = sorted(set(actual_norm) - set(golden_norm))

    # Also check type mismatches in matched columns
    type_mismatches = []
    for col in matched:
        if actual_norm[col] != golden_norm[col]:
            type_mismatches.append(f"{col}: {actual_norm[col]} != {golden_norm[col]}")

    return matched, missing, extra


class SQLValidator(BaseValidator):
    """Validate SQL files (DDL and ETL) using sqlglot parsing."""

    @property
    def name(self) -> str:
        return "sql"

    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]:
        check_type = check_config.get("type", "")

        if check_type == "ddl_structure":
            return self._check_ddl_structure(output_dir)
        if check_type == "ddl_columns_match":
            return self._check_ddl_columns(output_dir, golden_dir)
        if check_type == "etl_structure":
            return self._check_etl_structure(output_dir)
        if check_type == "ddl_etl_consistency":
            return self._check_ddl_etl_consistency(output_dir)
        if check_type == "comment_style":
            return self._check_comment_style(output_dir)

        return [
            CheckResult(
                check_type=check_type,
                status=CheckStatus.SKIP,
                detail=f"Unknown check type: {check_type}",
            )
        ]

    def _check_ddl_structure(self, output_dir: Path) -> list[CheckResult]:
        ddl_dir = output_dir / "04_ddl"
        if not ddl_dir.exists():
            return [
                CheckResult(
                    check_type="ddl_structure",
                    status=CheckStatus.FAIL,
                    detail="DDL directory not found",
                    evidence=str(ddl_dir),
                )
            ]

        files = _load_sql_files(ddl_dir, "*.sql")
        if not files:
            return [
                CheckResult(
                    check_type="ddl_structure",
                    status=CheckStatus.FAIL,
                    detail="No SQL files found in 04_ddl/",
                )
            ]

        results: list[CheckResult] = []
        for name, path, content in files:
            parsed = parse_ddl(content)
            if parsed is None:
                results.append(
                    CheckResult(
                        check_type="ddl_structure",
                        status=CheckStatus.FAIL,
                        detail=f"Failed to parse DDL: {name}",
                        evidence=f"Path: {path}",
                    )
                )
            else:
                col_count = len(parsed["columns"])
                results.append(
                    CheckResult(
                        check_type="ddl_structure",
                        status=CheckStatus.PASS,
                        detail=(
                            f"DDL parsed OK: {name} "
                            f"(table={parsed['table']}, columns={col_count})"
                        ),
                    )
                )
        return results

    def _check_ddl_columns(
        self, output_dir: Path, golden_dir: Path | None
    ) -> list[CheckResult]:
        if not golden_dir:
            return [
                CheckResult(
                    check_type="ddl_columns_match",
                    status=CheckStatus.SKIP,
                    detail="No golden_dir provided",
                )
            ]

        ddl_dir = output_dir / "04_ddl"
        golden_ddl_dir = golden_dir / "04_ddl"

        actual_files = _load_sql_files(ddl_dir, "*.sql")
        if not actual_files:
            return [
                CheckResult(
                    check_type="ddl_columns_match",
                    status=CheckStatus.FAIL,
                    detail="No DDL files found in output",
                )
            ]

        results: list[CheckResult] = []
        for name, _, content in actual_files:
            golden_path = golden_ddl_dir / name
            if not golden_path.exists():
                results.append(
                    CheckResult(
                        check_type="ddl_columns_match",
                        status=CheckStatus.SKIP,
                        detail=f"Golden DDL not found: {name}",
                    )
                )
                continue

            golden_content = golden_path.read_text(encoding="utf-8")
            actual_parsed = parse_ddl(content)
            golden_parsed = parse_ddl(golden_content)

            if actual_parsed is None or golden_parsed is None:
                results.append(
                    CheckResult(
                        check_type="ddl_columns_match",
                        status=CheckStatus.FAIL,
                        detail=f"Parse error for {name} (actual or golden)",
                    )
                )
                continue

            matched, missing, extra = _compare_column_dicts(
                actual_parsed["columns"], golden_parsed["columns"]
            )

            if not missing and not extra:
                results.append(
                    CheckResult(
                        check_type="ddl_columns_match",
                        status=CheckStatus.PASS,
                        detail=f"Columns match: {name} ({len(matched)} columns)",
                    )
                )
            else:
                detail_parts = []
                if missing:
                    detail_parts.append(f"missing={missing}")
                if extra:
                    detail_parts.append(f"extra={extra}")
                results.append(
                    CheckResult(
                        check_type="ddl_columns_match",
                        status=CheckStatus.FAIL,
                        detail=f"Column mismatch in {name}: {', '.join(detail_parts)}",
                        evidence=f"Matched: {matched}",
                    )
                )

        return results

    def _check_etl_structure(self, output_dir: Path) -> list[CheckResult]:
        etl_dir = output_dir / "05_etl"
        if not etl_dir.exists():
            return [
                CheckResult(
                    check_type="etl_structure",
                    status=CheckStatus.FAIL,
                    detail="ETL directory not found",
                    evidence=str(etl_dir),
                )
            ]

        files = _load_sql_files(etl_dir, "*.sql")
        if not files:
            return [
                CheckResult(
                    check_type="etl_structure",
                    status=CheckStatus.FAIL,
                    detail="No SQL files found in 05_etl/",
                )
            ]

        results: list[CheckResult] = []
        for name, path, content in files:
            parsed = parse_etl(content)
            if parsed is None:
                results.append(
                    CheckResult(
                        check_type="etl_structure",
                        status=CheckStatus.FAIL,
                        detail=f"Failed to parse ETL: {name}",
                        evidence=f"Path: {path}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_type="etl_structure",
                        status=CheckStatus.PASS,
                        detail=(
                            f"ETL parsed OK: {name} "
                            f"(target={parsed['target_table']}, "
                            f"insert_cols={len(parsed['insert_columns'])})"
                        ),
                    )
                )
        return results

    def _check_ddl_etl_consistency(self, output_dir: Path) -> list[CheckResult]:
        """Check that DDL column count matches ETL INSERT column count."""
        ddl_dir = output_dir / "04_ddl"
        etl_dir = output_dir / "05_etl"

        ddl_files = _load_sql_files(ddl_dir, "*.sql")
        etl_files = _load_sql_files(etl_dir, "*.sql")

        if not ddl_files or not etl_files:
            return [
                CheckResult(
                    check_type="ddl_etl_consistency",
                    status=CheckStatus.SKIP,
                    detail="Missing DDL or ETL files",
                )
            ]

        # Build DDL column counts keyed by table name
        ddl_col_counts: dict[str, int] = {}
        for _, _, content in ddl_files:
            parsed = parse_ddl(content)
            if parsed:
                ddl_col_counts[parsed["table"]] = len(parsed["columns"])

        results: list[CheckResult] = []
        for name, _, content in etl_files:
            parsed = parse_etl(content)
            if not parsed:
                continue

            target = parsed["target_table"]
            insert_count = len(parsed["insert_columns"])
            ddl_count = ddl_col_counts.get(target)

            if ddl_count is None:
                results.append(
                    CheckResult(
                        check_type="ddl_etl_consistency",
                        status=CheckStatus.SKIP,
                        detail=f"No matching DDL for target table: {target}",
                    )
                )
            elif insert_count == ddl_count:
                results.append(
                    CheckResult(
                        check_type="ddl_etl_consistency",
                        status=CheckStatus.PASS,
                        detail=(
                            f"{name}: INSERT columns ({insert_count}) "
                            f"match DDL columns ({ddl_count})"
                        ),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_type="ddl_etl_consistency",
                        status=CheckStatus.FAIL,
                        detail=(
                            f"{name}: INSERT columns ({insert_count}) "
                            f"!= DDL columns ({ddl_count})"
                        ),
                    )
                )

        return results

    def _check_comment_style(self, output_dir: Path) -> list[CheckResult]:
        results: list[CheckResult] = []
        sql_dirs = ["04_ddl", "05_etl", "04_ddl_rollback"]

        for dir_name in sql_dirs:
            sql_dir = output_dir / dir_name
            if not sql_dir.exists():
                continue
            for sql_file in sorted(sql_dir.glob("*.sql")):
                content = sql_file.read_text(encoding="utf-8")
                violations = []
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.lstrip()
                    if not stripped.startswith("--"):
                        continue
                    if stripped.upper().startswith("COMMENT ON"):
                        continue
                    violations.append((i, stripped))

                if violations:
                    lines = ", ".join(f"L{ln}" for ln, _ in violations[:5])
                    results.append(
                        CheckResult(
                            check_type="comment_style",
                            status=CheckStatus.FAIL,
                            detail=(
                                f"{dir_name}/{sql_file.name}: "
                                f"found {len(violations)} -- comment(s) "
                                f"({lines}), use /* */ instead"
                            ),
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            check_type="comment_style",
                            status=CheckStatus.PASS,
                            detail=f"{dir_name}/{sql_file.name}: no -- comments",
                        )
                    )

        return results
