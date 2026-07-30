"""Review validator — extract review conclusions from review reports."""

from __future__ import annotations

import re
from pathlib import Path

from .base import BaseValidator, CheckResult, CheckStatus

# Patterns for review conclusion extraction
_RE_CRITICAL = re.compile(r"\|\s*CRITICAL\s*\|\s*(\d+)\s*\|")
_RE_MAJOR = re.compile(r"\|\s*MAJOR\s*\|\s*(\d+)\s*\|")
_RE_MINOR = re.compile(r"\|\s*MINOR\s*\|\s*(\d+)\s*\|")
_RE_SUGGESTION = re.compile(r"\|\s*SUGGESTION\s*\|\s*(\d+)\s*\|")
_RE_CONCLUSION = re.compile(
    r"\*\*最终结论\*\*[：:]\s*(✅\s*通过|❌\s*不通过|⚠️\s*需确认)"
)
_RE_STOP_FLAG = re.compile(
    r"\*\*停止标志\*\*[：:]\s*(STOP|CONTINUE|NEED_CONFIRM)"
)
_RE_STATUS_BLOCK_START = re.compile(
    r"---\s*\n\s*##\s*📊\s*评审结论"
)


def extract_review_stats(text: str) -> dict | None:
    """Extract review statistics from a review markdown file.

    Returns dict with keys: critical, major, minor, suggestion,
    conclusion, stop_flag. Returns None if no valid stats found.
    """
    critical = _RE_CRITICAL.search(text)
    major = _RE_MAJOR.search(text)
    minor = _RE_MINOR.search(text)
    suggestion = _RE_SUGGESTION.search(text)

    # At least one severity count must be present
    if not any([critical, major, minor, suggestion]):
        return None

    conclusion_m = _RE_CONCLUSION.search(text)
    stop_flag_m = _RE_STOP_FLAG.search(text)

    return {
        "critical": int(critical.group(1)) if critical else 0,
        "major": int(major.group(1)) if major else 0,
        "minor": int(minor.group(1)) if minor else 0,
        "suggestion": int(suggestion.group(1)) if suggestion else 0,
        "conclusion": conclusion_m.group(1) if conclusion_m else None,
        "stop_flag": stop_flag_m.group(1) if stop_flag_m else None,
    }


class ReviewValidator(BaseValidator):
    """Validate review report format and extract conclusions."""

    @property
    def name(self) -> str:
        return "review"

    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]:
        check_type = check_config.get("type", "")
        review_file = check_config.get("file", "")

        # Determine which review file to check
        if review_file:
            review_path = output_dir / review_file
        else:
            # Try common locations
            review_path = self._find_review_file(output_dir)

        if not review_path or not review_path.exists():
            return [
                CheckResult(
                    check_type=check_type or "review_format",
                    status=CheckStatus.FAIL,
                    detail="Review file not found",
                    evidence=f"Tried: {review_path}",
                )
            ]

        text = review_path.read_text(encoding="utf-8")

        if check_type == "review_format":
            return self._check_format(text, review_path.name)
        if check_type == "review_conclusion":
            expected = check_config.get("expected")
            return self._check_conclusion(text, review_path.name, expected)
        if check_type == "review_mentions":
            keywords = check_config.get("keywords")
            return self._check_mentions(text, review_path.name, keywords)

        return [
            CheckResult(
                check_type=check_type,
                status=CheckStatus.SKIP,
                detail=f"Unknown check type: {check_type}",
            )
        ]

    def _find_review_file(self, output_dir: Path) -> Path | None:
        """Find a review markdown file in common locations."""
        candidates = [
            output_dir / "03_design_review" / "design_review.md",
            output_dir / "07_code_review" / "code_review.md",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _check_format(self, text: str, filename: str) -> list[CheckResult]:
        """Check that the status block exists in the review file."""
        has_status_block = bool(_RE_STATUS_BLOCK_START.search(text))
        stats = extract_review_stats(text)

        if has_status_block and stats:
            return [
                CheckResult(
                    check_type="review_format",
                    status=CheckStatus.PASS,
                    detail=f"Valid review format: {filename}",
                    evidence=f"Stats: CRITICAL={stats['critical']}, "
                    f"MAJOR={stats['major']}, "
                    f"MINOR={stats['minor']}, "
                    f"SUGGESTION={stats['suggestion']}",
                )
            ]

        issues = []
        if not has_status_block:
            issues.append("missing status block (---\\n## 📊 评审结论)")
        if stats is None:
            issues.append("no severity counts found")

        return [
            CheckResult(
                check_type="review_format",
                status=CheckStatus.FAIL,
                detail=f"Invalid review format: {filename} — {'; '.join(issues)}",
            )
        ]

    def _check_conclusion(
        self, text: str, filename: str, expected: dict | None = None
    ) -> list[CheckResult]:
        """Extract review conclusion and optionally compare against expected values.

        expected dict supports:
          - stop_flag: exact match (e.g. "STOP", "CONTINUE")
          - critical: exact match
          - critical_ge: minimum value (e.g. 1 means critical >= 1)
          - major: exact match
          - major_ge: minimum value
        """
        stats = extract_review_stats(text)

        if stats is None:
            return [
                CheckResult(
                    check_type="review_conclusion",
                    status=CheckStatus.FAIL,
                    detail=f"No review stats found in {filename}",
                )
            ]

        conclusion = stats["conclusion"] or "unknown"
        stop_flag = stats["stop_flag"] or "unknown"
        evidence = (
            f"critical={stats['critical']}, major={stats['major']}, "
            f"minor={stats['minor']}, suggestion={stats['suggestion']}, "
            f"conclusion={conclusion}, stop_flag={stop_flag}"
        )

        # If no expected values, just report what was found (always pass)
        if not expected:
            return [
                CheckResult(
                    check_type="review_conclusion",
                    status=CheckStatus.PASS,
                    detail=f"{filename}: {conclusion} (flag={stop_flag})",
                    evidence=evidence,
                )
            ]

        # Compare against expected values
        mismatches: list[str] = []

        # stop_flag: exact match
        if "stop_flag" in expected:
            exp_flag = expected["stop_flag"]
            if stop_flag != exp_flag:
                mismatches.append(
                    f"stop_flag: expected={exp_flag}, actual={stop_flag}"
                )

        # critical: exact match
        if "critical" in expected:
            exp_val = expected["critical"]
            if stats["critical"] != exp_val:
                mismatches.append(
                    f"critical: expected={exp_val}, actual={stats['critical']}"
                )

        # critical_ge: minimum threshold
        if "critical_ge" in expected:
            threshold = expected["critical_ge"]
            if stats["critical"] < threshold:
                mismatches.append(
                    f"critical: expected>={threshold}, actual={stats['critical']}"
                )

        # major: exact match
        if "major" in expected:
            exp_val = expected["major"]
            if stats["major"] != exp_val:
                mismatches.append(
                    f"major: expected={exp_val}, actual={stats['major']}"
                )

        # major_ge: minimum threshold
        if "major_ge" in expected:
            threshold = expected["major_ge"]
            if stats["major"] < threshold:
                mismatches.append(
                    f"major: expected>={threshold}, actual={stats['major']}"
                )

        if mismatches:
            return [
                CheckResult(
                    check_type="review_conclusion",
                    status=CheckStatus.FAIL,
                    detail=f"{filename}: {'; '.join(mismatches)}",
                    evidence=evidence,
                )
            ]

        return [
            CheckResult(
                check_type="review_conclusion",
                status=CheckStatus.PASS,
                detail=f"{filename}: {conclusion} matches expected (flag={stop_flag})",
                evidence=evidence,
            )
        ]

    def _check_mentions(
        self, text: str, filename: str, keywords: list[str] | None = None
    ) -> list[CheckResult]:
        """Check that review report mentions specific keywords.

        This verifies the reviewer actually identified the right problem,
        not just gave a generic conclusion.
        """
        if not keywords:
            return [
                CheckResult(
                    check_type="review_mentions",
                    status=CheckStatus.SKIP,
                    detail="No keywords specified",
                )
            ]

        results: list[CheckResult] = []
        for kw in keywords:
            found = kw in text
            results.append(
                CheckResult(
                    check_type="review_mentions",
                    status=CheckStatus.PASS if found else CheckStatus.FAIL,
                    detail=(
                        f"{'Found' if found else 'Missing'} keyword "
                        f"'{kw}' in {filename}"
                    ),
                    evidence=f"keyword='{kw}'" if found else "",
                )
            )

        return results
