"""Stable contracts shared by the governed execution kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class Principal:
    """Trusted identity created only after an upstream authenticator validates it."""

    user_id: str
    org_id: str
    roles: frozenset[str] = frozenset()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _required_text(self.user_id, "user_id"))
        object.__setattr__(self, "org_id", _required_text(self.org_id, "org_id"))
        normalized_roles = frozenset(
            _required_text(role, "role").lower() for role in self.roles
        )
        object.__setattr__(self, "roles", normalized_roles)
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True, slots=True)
class TenantBinding:
    """Server-owned mapping from an organization/database pair to a data source."""

    org_id: str
    database_id: str
    connector_id: str
    target: str

    def __post_init__(self) -> None:
        for field_name in ("org_id", "database_id", "connector_id", "target"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """A typed request for one governed capability invocation."""

    principal: Principal
    capability: str
    database_id: str
    tables: tuple[str, ...] = ()
    columns: frozenset[str] = frozenset()
    purpose: str = "analytical_read"
    task_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability", _required_text(self.capability, "capability")
        )
        object.__setattr__(
            self, "database_id", _required_text(self.database_id, "database_id")
        )
        object.__setattr__(
            self,
            "tables",
            tuple(_required_text(table, "table").lower() for table in self.tables),
        )
        object.__setattr__(
            self,
            "columns",
            frozenset(_required_text(column, "column").lower() for column in self.columns),
        )
        object.__setattr__(self, "purpose", _required_text(self.purpose, "purpose"))


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Model-independent, read-only query plan submitted to the kernel."""

    sql: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.sql, str) or not self.sql.strip():
            raise ValueError("sql must be a non-empty string")
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Bounded result returned by a governed execution."""

    rows: tuple[Mapping[str, Any], ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only event emitted for every kernel decision and execution."""

    event_type: str
    user_id: str
    org_id: str
    capability: str
    database_id: str
    decision: str
    reason: str
    query_hash: str | None = None
    task_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        for field_name in (
            "event_type",
            "user_id",
            "org_id",
            "capability",
            "database_id",
            "decision",
            "reason",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
