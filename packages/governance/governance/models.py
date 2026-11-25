"""Append-only governance event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class GovernanceEvent:
    """A tenant-scoped event describing a control-plane state change."""

    org_id: str
    event_type: str
    actor_user_id: str
    decision: str
    reason: str
    task_id: str | None = None
    approval_id: str | None = None
    capability: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        for field_name in (
            "org_id",
            "event_type",
            "actor_user_id",
            "decision",
            "reason",
            "event_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        for field_name in ("task_id", "approval_id", "capability"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _required_text(value, field_name))
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include timezone information")
        object.__setattr__(self, "payload", dict(self.payload))
