"""Typed, tenant-scoped memory contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from execution_kernel import Principal


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


class MemoryScope(StrEnum):
    """The principal boundary in which a memory may be used."""

    TASK = "task"
    USER = "user"
    TENANT = "tenant"


class MemoryClassification(StrEnum):
    """Sensitivity classification carried with every memory record."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RetentionClass(StrEnum):
    """Retention intent; durable adapters must enforce the same contract."""

    EPHEMERAL = "ephemeral"
    TASK = "task"
    STANDARD = "standard"
    LONG_TERM = "long_term"


@dataclass(frozen=True, slots=True)
class MemoryRetention:
    policy: RetentionClass
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy, RetentionClass):
            raise ValueError("policy must be a RetentionClass")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if self.policy in (RetentionClass.EPHEMERAL, RetentionClass.TASK):
            if self.expires_at is None:
                raise ValueError(f"{self.policy.value} retention requires expires_at")

    def is_active(self, now: datetime | None = None) -> bool:
        return self.expires_at is None or (now or datetime.now(timezone.utc)) < self.expires_at


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    """The source and actor that made a memory eligible for storage."""

    source: str
    source_id: str
    recorded_by: str
    reason: str

    def __post_init__(self) -> None:
        for field_name in ("source", "source_id", "recorded_by", "reason"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """Immutable memory data with explicit tenant, scope, and retention metadata."""

    org_id: str
    scope: MemoryScope
    scope_id: str
    content: str
    classification: MemoryClassification
    retention: MemoryRetention
    provenance: MemoryProvenance
    owner_user_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "org_id", _required_text(self.org_id, "org_id"))
        object.__setattr__(self, "scope_id", _required_text(self.scope_id, "scope_id"))
        object.__setattr__(self, "content", _required_text(self.content, "content"))
        object.__setattr__(self, "memory_id", _required_text(self.memory_id, "memory_id"))
        if not isinstance(self.scope, MemoryScope):
            raise ValueError("scope must be a MemoryScope")
        if not isinstance(self.classification, MemoryClassification):
            raise ValueError("classification must be a MemoryClassification")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include timezone information")
        if self.scope in (MemoryScope.USER, MemoryScope.TASK) and not self.owner_user_id:
            raise ValueError(f"{self.scope.value}-scoped memory requires owner_user_id")
        if self.owner_user_id is not None:
            object.__setattr__(
                self, "owner_user_id", _required_text(self.owner_user_id, "owner_user_id")
            )
        object.__setattr__(self, "metadata", dict(self.metadata))


class MemoryAuthorizer:
    """Default fail-closed authorization boundary for memory operations."""

    def can_write(self, principal: Principal, record: MemoryRecord) -> bool:
        return self._same_tenant(principal, record) and self._owns_scope(principal, record)

    def can_read(self, principal: Principal, record: MemoryRecord) -> bool:
        return self._same_tenant(principal, record) and self._owns_scope(principal, record)

    @staticmethod
    def _same_tenant(principal: Principal, record: MemoryRecord) -> bool:
        return principal.org_id == record.org_id

    @staticmethod
    def _owns_scope(principal: Principal, record: MemoryRecord) -> bool:
        return record.scope is MemoryScope.TENANT or (
            record.owner_user_id == principal.user_id
        )
