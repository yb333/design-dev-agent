"""Artifact validator — file existence, count, and naming pattern checks."""

from __future__ import annotations

from pathlib import Path

from .base import BaseValidator, CheckResult, CheckStatus


class ArtifactValidator(BaseValidator):
    """Validate that expected output files exist and are non-empty."""

    @property
    def name(self) -> str:
        return "artifact"

    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]:
        check_type = check_config.get("type", "files_exist")
        paths = check_config.get("paths", [])

        if check_type == "files_exist":
            return self._check_files_exist(paths, output_dir)

        return [
            CheckResult(
                check_type=check_type,
                status=CheckStatus.SKIP,
                detail=f"Unknown check type: {check_type}",
            )
        ]

    def _check_files_exist(
        self, paths: list[str], output_dir: Path
    ) -> list[CheckResult]:
        results: list[CheckResult] = []
        for pattern in paths:
            results.append(self._check_single_path(pattern, output_dir))
        return results

    def _check_single_path(self, pattern: str, output_dir: Path) -> CheckResult:
        has_wildcard = "*" in pattern and "**" not in pattern

        if has_wildcard:
            matched = self._glob_match(pattern, output_dir)
            if not matched:
                return CheckResult(
                    check_type="files_exist",
                    status=CheckStatus.FAIL,
                    detail=f"No files match '{pattern}'",
                    evidence=f"Searched in: {output_dir / pattern}",
                )
            names = ", ".join(f.name for f in matched)
            return CheckResult(
                check_type="files_exist",
                status=CheckStatus.PASS,
                detail=f"Found {len(matched)} file(s) matching '{pattern}': {names}",
                evidence=names,
            )

        # Exact file path — check existence AND non-empty
        target = output_dir / pattern
        if not target.exists():
            return CheckResult(
                check_type="files_exist",
                status=CheckStatus.FAIL,
                detail=f"File not found: {pattern}",
                evidence=f"Expected at: {target}",
            )
        if target.stat().st_size == 0:
            return CheckResult(
                check_type="files_exist",
                status=CheckStatus.FAIL,
                detail=f"File exists but is empty: {pattern}",
                evidence=f"Path: {target}, size: 0 bytes",
            )
        return CheckResult(
            check_type="files_exist",
            status=CheckStatus.PASS,
            detail=f"File exists and non-empty: {pattern}",
            evidence=f"Path: {target}, size: {target.stat().st_size} bytes",
        )
