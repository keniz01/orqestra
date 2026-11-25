"""Transport-independent workflow reliability contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def _text(name: str, value: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds the maximum length")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must include timezone information")
    return value


class ReliabilityError(RuntimeError):
    """Base class for reliability contract failures."""


class LeaseStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Lease:
    """A time-bounded, exclusively owned workflow lease."""

    workflow_id: str
    lease_id: str
    owner_id: str
    expires_at: datetime
    version: int = 0

    def __post_init__(self) -> None:
        _text("workflow_id", self.workflow_id)
        _text("lease_id", self.lease_id)
        _text("owner_id", self.owner_id)
        _aware(self.expires_at, "expires_at")
        if self.version < 0:
            raise ValueError("version must not be negative")

    def is_active(self, now: datetime | None = None) -> bool:
        current = _aware(now, "now") if now is not None else datetime.now(timezone.utc)
        return current < self.expires_at

    @property
    def status(self) -> LeaseStatus:
        return LeaseStatus.ACTIVE if self.is_active() else LeaseStatus.EXPIRED


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must not be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least one")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError(
                "max_delay_seconds must not be less than initial_delay_seconds"
            )

    def can_retry(self, attempts: int) -> bool:
        if attempts < 0:
            raise ValueError("attempts must not be negative")
        return attempts < self.max_attempts

    def delay_for(self, attempts: int) -> float:
        if attempts < 0:
            raise ValueError("attempts must not be negative")
        delay = self.initial_delay_seconds * (self.backoff_multiplier**attempts)
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """The result associated with one validated request fingerprint."""

    key: str
    request_hash: str
    response: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _text("key", self.key)
        _text("request_hash", self.request_hash, max_length=512)
        _aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Cancellation:
    """An immutable cancellation request for a workflow."""

    workflow_id: str
    reason: str = "Cancellation requested."
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1

    def __post_init__(self) -> None:
        _text("workflow_id", self.workflow_id)
        _text("reason", self.reason, max_length=1024)
        _aware(self.requested_at, "requested_at")
        if self.version < 1:
            raise ValueError("version must be at least one")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """An immutable version of workflow state suitable for recovery."""

    workflow_id: str
    checkpoint_id: str
    version: int
    state: Mapping[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _text("workflow_id", self.workflow_id)
        _text("checkpoint_id", self.checkpoint_id)
        if self.version < 1:
            raise ValueError("version must be at least one")
        if not isinstance(self.state, Mapping):
            raise ValueError("state must be a mapping")
        _aware(self.created_at, "created_at")
        object.__setattr__(self, "state", dict(self.state))
