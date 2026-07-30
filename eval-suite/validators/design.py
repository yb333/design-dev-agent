"""Design validator — extract structured decisions from design.md and compare."""

from __future__ import annotations

import re
from pathlib import Path

from .base import BaseValidator, CheckResult, CheckStatus

# Required audit fields
AUDIT_FIELDS = {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"}

# Required section headers (minimum presence)
REQUIRED_SECTIONS = [
    "## 1. 概述",
    "## 2. 复杂度分析",
    "## 3. 表级血缘",
    "## 4. 分段策略",
]

# Regex patterns
_FIELD_MAPPING_HEADER = re.compile(
    r"\|\s*目标字段\s*\|\s*目标类型\s*\|\s*来源字段\s*\|\s*源类型"
    r"\s*\|\s*来源表\s*\|\s*映射规则\s*\|\s*转换逻辑\s*\|"
)
_STEP_HEADER = re.compile(r"###\s+步骤\s+\d+\s*[：:]\s*(.+)")
_DIST_KEY = re.compile(r"\*\*分布键\*\*[：:]\s*(.+)")
_TABLE_ROW = re.compile(
    r"\|\s*\d+\s*\|\s*\[?(\w+\.\w+)\]?"
)
_OVERVIEW_TARGET = re.compile(r"\|\s*\*\*目标表\*\*\s*\|\s*\[?(\w+\.\w+)\]?")
_OVERVIEW_SEGMENTS = re.compile(r"\|\s*\*\*分段数\*\*\s*\|\s*(\d+)")
_OVERVIEW_FIELDS = re.compile(
    r"\|\s*\*\*字段统计\*\*\s*\|\s*业务\s*(\d+)\s*\+\s*审计\s*4\s*=\s*总计\s*(\d+)"
)


def _extract_field_mappings(text: str) -> set[tuple[str, str]]:
    """Extract (source_field, target_field) pairs from all field mapping tables."""
    pairs: set[tuple[str, str]] = set()
    lines = text.split("\n")
    in_mapping_table = False
    found_header = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_mapping_table = False
            found_header = False
            continue

        if _FIELD_MAPPING_HEADER.search(stripped):
            in_mapping_table = True
            found_header = True
            continue

        # Skip separator row
        if re.match(r"^\|[\s\-|]+\|$", stripped):
            continue

        if in_mapping_table and found_header:
            cells = [c.strip() for c in stripped.split("|")]
            # Remove empty strings from leading/trailing splits
            cells = [c for c in cells if c != ""]
            if len(cells) >= 7:
                target_field = cells[0]
                source_field = cells[2]
                if target_field and source_field:
                    pairs.add((source_field, target_field))

    return pairs


def _extract_segments(text: str) -> int:
    """Count the number of step headers (### 步骤 N:)."""
    return len(_STEP_HEADER.findall(text))


def _extract_distribution_keys(text: str) -> dict[str, str]:
    """Extract distribution key per step."""
    lines = text.split("\n")
    result: dict[str, str] = {}
    current_step: str | None = None

    for line in lines:
        step_match = _STEP_HEADER.search(line)
        if step_match:
            current_step = step_match.group(1).strip()
            continue

        if current_step:
            dk_match = _DIST_KEY.search(line)
            if dk_match:
                result[current_step] = dk_match.group(1).strip()

    return result


def _check_audit_fields(text: str) -> bool:
    """Check if all 4 audit fields appear in every field mapping table."""
    tables = _split_mapping_tables(text)
    if not tables:
        return False

    for table_text in tables:
        for audit_field in AUDIT_FIELDS:
            found = False
            for row in table_text.split("\n"):
                if not row.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in row.split("|")]
                cells = [c for c in cells if c != ""]
                if len(cells) >= 1 and cells[0] == audit_field:
                    found = True
                    break
            if not found:
                return False
    return True


def _split_mapping_tables(text: str) -> list[str]:
    """Split text into individual field mapping table blocks."""
    tables: list[str] = []
    lines = text.split("\n")
    current_table: list[str] = []
    in_table = False

    for line in lines:
        if _FIELD_MAPPING_HEADER.search(line):
            in_table = True
            current_table = [line]
            continue

        if in_table:
            if line.strip().startswith("|"):
                current_table.append(line)
            else:
                if current_table:
                    tables.append("\n".join(current_table))
                in_table = False
                current_table = []

    if current_table:
        tables.append("\n".join(current_table))

    return tables


def _extract_source_tables(text: str) -> set[str]:
    """Extract source tables from the 来源表 table in section 1."""
    tables: set[str] = set()
    lines = text.split("\n")
    in_source_table = False

    for line in lines:
        if "来源表" in line and line.strip().startswith("|") and "表名" in line:
            in_source_table = True
            continue

        if in_source_table:
            if not line.strip().startswith("|"):
                break
            match = _TABLE_ROW.search(line)
            if match:
                tables.add(match.group(1))

    return tables


def _extract_overview(text: str) -> dict:
    """Extract overview fields from section 1."""
    overview: dict = {}
    lines = text.split("\n")

    for line in lines:
        m_target = _OVERVIEW_TARGET.search(line)
        if m_target:
            overview["target_table"] = m_target.group(1)

        m_seg = _OVERVIEW_SEGMENTS.search(line)
        if m_seg:
            overview["segment_count"] = int(m_seg.group(1))

        m_fields = _OVERVIEW_FIELDS.search(line)
        if m_fields:
            overview["business_fields"] = int(m_fields.group(1))
            overview["total_fields"] = int(m_fields.group(2))

    return overview


class DesignValidator(BaseValidator):
    """Validate design.md structure and content."""

    @property
    def name(self) -> str:
        return "design"

    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]:
        check_type = check_config.get("type", "")
        design_path = output_dir / "02_design" / "design.md"

        if not design_path.exists():
            return [
                CheckResult(
                    check_type=check_type or "design_structure",
                    status=CheckStatus.FAIL,
                    detail="design.md not found",
                    evidence=f"Expected at: {design_path}",
                )
            ]

        text = design_path.read_text(encoding="utf-8")

        if check_type == "design_structure":
            return self._check_structure(text)
        if check_type == "field_mapping_match":
            return self._check_field_mapping(text, golden_dir)
        if check_type == "audit_fields_present":
            return self._check_audit(text)
        if check_type == "segment_strategy":
            return self._check_segments(text, golden_dir)

        return [
            CheckResult(
                check_type=check_type,
                status=CheckStatus.SKIP,
                detail=f"Unknown check type: {check_type}",
            )
        ]

    def _check_structure(self, text: str) -> list[CheckResult]:
        results: list[CheckResult] = []
        for section in REQUIRED_SECTIONS:
            if section in text:
                results.append(
                    CheckResult(
                        check_type="design_structure",
                        status=CheckStatus.PASS,
                        detail=f"Section present: {section}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_type="design_structure",
                        status=CheckStatus.FAIL,
                        detail=f"Section missing: {section}",
                    )
                )
        return results

    def _check_field_mapping(
        self, text: str, golden_dir: Path | None
    ) -> list[CheckResult]:
        if not golden_dir:
            return [
                CheckResult(
                    check_type="field_mapping_match",
                    status=CheckStatus.SKIP,
                    detail="No golden_dir provided, cannot compare field mappings",
                )
            ]

        golden_design = golden_dir / "02_design" / "design.md"
        if not golden_design.exists():
            return [
                CheckResult(
                    check_type="field_mapping_match",
                    status=CheckStatus.SKIP,
                    detail=f"Golden design.md not found at {golden_design}",
                )
            ]

        golden_text = golden_design.read_text(encoding="utf-8")
        actual_mappings = _extract_field_mappings(text)
        golden_mappings = _extract_field_mappings(golden_text)

        if actual_mappings == golden_mappings:
            return [
                CheckResult(
                    check_type="field_mapping_match",
                    status=CheckStatus.PASS,
                    detail=f"Field mappings match ({len(actual_mappings)} pairs)",
                )
            ]

        missing = golden_mappings - actual_mappings
        extra = actual_mappings - golden_mappings
        detail_parts = [f"actual={len(actual_mappings)}, golden={len(golden_mappings)}"]
        if missing:
            detail_parts.append(f"missing={len(missing)}")
        if extra:
            detail_parts.append(f"extra={len(extra)}")

        return [
            CheckResult(
                check_type="field_mapping_match",
                status=CheckStatus.FAIL,
                detail=f"Field mappings differ: {', '.join(detail_parts)}",
                evidence=f"Missing: {sorted(missing)} | Extra: {sorted(extra)}",
            )
        ]

    def _check_audit(self, text: str) -> list[CheckResult]:
        present = _check_audit_fields(text)
        return [
            CheckResult(
                check_type="audit_fields_present",
                status=CheckStatus.PASS if present else CheckStatus.FAIL,
                detail=(
                    f"All 4 audit fields present in all mapping tables"
                    if present
                    else "Missing audit fields in one or more mapping tables"
                ),
                evidence=f"Audit fields checked: {sorted(AUDIT_FIELDS)}",
            )
        ]

    def _check_segments(
        self, text: str, golden_dir: Path | None
    ) -> list[CheckResult]:
        if not golden_dir:
            return [
                CheckResult(
                    check_type="segment_strategy",
                    status=CheckStatus.SKIP,
                    detail="No golden_dir provided, cannot compare segment count",
                )
            ]

        golden_design = golden_dir / "02_design" / "design.md"
        if not golden_design.exists():
            return [
                CheckResult(
                    check_type="segment_strategy",
                    status=CheckStatus.SKIP,
                    detail=f"Golden design.md not found at {golden_design}",
                )
            ]

        golden_text = golden_design.read_text(encoding="utf-8")
        actual_count = _extract_segments(text)
        golden_count = _extract_segments(golden_text)

        if actual_count == golden_count:
            return [
                CheckResult(
                    check_type="segment_strategy",
                    status=CheckStatus.PASS,
                    detail=f"Segment count matches: {actual_count}",
                )
            ]

        return [
            CheckResult(
                check_type="segment_strategy",
                status=CheckStatus.FAIL,
                detail=f"Segment count differs: actual={actual_count}, golden={golden_count}",
            )
        ]
