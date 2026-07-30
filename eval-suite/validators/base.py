"""Base validator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CheckStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Single check result."""

    check_type: str
    status: CheckStatus
    detail: str
    evidence: str = ""
    score: float | None = None

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "check_type": self.check_type,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": self.evidence,
        }
        if self.score is not None:
            d["score"] = self.score
        return d


class BaseValidator(ABC):
    """Base class for all validators."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def validate(
        self,
        check_config: dict,
        output_dir: Path,
        golden_dir: Path | None = None,
    ) -> list[CheckResult]: ...

    def _glob_match(self, pattern: str, base_dir: Path) -> list[Path]:
        """Match glob pattern against directory, supporting * but NOT **."""
        if "*" in pattern:
            parent = (
                base_dir / pattern.rsplit("/", 1)[0] if "/" in pattern else base_dir
            )
            if not parent.exists():
                return []
            return sorted(parent.glob(pattern.split("/")[-1]))
        path = base_dir / pattern
        return [path] if path.exists() else []
