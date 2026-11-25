"""Typed metadata contracts for the tenant-scoped semantic catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum, StrEnum


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


class Classification(IntEnum):
    """Ordered sensitivity levels used by catalog policies."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


class SourceKind(StrEnum):
    DATABASE = "database"
    FILE = "file"
    API = "api"
    WAREHOUSE = "warehouse"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Evidence describing where a metadata record came from."""

    source_system: str
    source_object: str
    collected_at: datetime
    collector: str

    def __post_init__(self) -> None:
        for field_name in ("source_system", "source_object", "collector"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        _aware(self.collected_at, "collected_at")


@dataclass(frozen=True, slots=True)
class Freshness:
    """Freshness expectation and observation for a metadata record."""

    last_refreshed_at: datetime
    max_age: timedelta

    def __post_init__(self) -> None:
        _aware(self.last_refreshed_at, "last_refreshed_at")
        if self.max_age <= timedelta(0):
            raise ValueError("max_age must be positive")

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        current = _aware(as_of or datetime.now(timezone.utc), "as_of")
        return current - self.last_refreshed_at <= self.max_age


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    tenant_id: str
    source_id: str
    table_id: str
    name: str
    data_type: str
    classification: Classification = Classification.INTERNAL
    nullable: bool = True
    description: str = ""
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "source_id", "table_id", "name", "data_type"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")


@dataclass(frozen=True, slots=True)
class TableMetadata:
    tenant_id: str
    source_id: str
    table_id: str
    name: str
    classification: Classification = Classification.INTERNAL
    description: str = ""
    columns: tuple[ColumnMetadata, ...] = ()
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "source_id", "table_id", "name"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")
        columns = tuple(self.columns)
        if any(
            column.tenant_id != self.tenant_id
            or column.source_id != self.source_id
            or column.table_id != self.table_id
            for column in columns
        ):
            raise ValueError("columns must belong to their table and tenant")
        object.__setattr__(self, "columns", columns)


@dataclass(frozen=True, slots=True)
class DataSourceMetadata:
    tenant_id: str
    source_id: str
    name: str
    kind: SourceKind
    classification: Classification = Classification.INTERNAL
    description: str = ""
    tables: tuple[TableMetadata, ...] = ()
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "source_id", "name"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.kind, SourceKind):
            raise ValueError("kind must be a SourceKind")
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")
        tables = tuple(self.tables)
        if any(
            table.tenant_id != self.tenant_id or table.source_id != self.source_id
            for table in tables
        ):
            raise ValueError("tables must belong to their source and tenant")
        object.__setattr__(self, "tables", tables)


# Short names are convenient for callers while the Metadata names remain explicit.
DataSource = DataSourceMetadata
Table = TableMetadata
Column = ColumnMetadata
