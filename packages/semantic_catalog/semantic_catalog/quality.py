"""Freshness and quality metadata for semantic catalog facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import _aware, _required_text


class QualityStatus(StrEnum):
    UNKNOWN = "unknown"
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class QualityMetadata:
    fact_id: str
    status: QualityStatus
    observed_at: datetime
    completeness: float | None = None
    uniqueness: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _required_text(self.fact_id, "fact_id"))
        if not isinstance(self.status, QualityStatus):
            raise ValueError("status must be a QualityStatus")
        _aware(self.observed_at, "observed_at")
        for field_name in ("completeness", "uniqueness"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")
        object.__setattr__(self, "notes", self.notes.strip())
