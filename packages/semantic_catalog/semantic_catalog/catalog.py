"""In-memory reference implementation of the semantic catalog contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from execution_kernel import Principal

from .models import (
    Classification,
    ColumnMetadata,
    DataSourceMetadata,
    TableMetadata,
)


class CatalogScopeError(PermissionError):
    """Raised when a catalog record is outside the caller's tenant."""


class CatalogConflict(ValueError):
    """Raised when a tenant already has a source with the same identifier."""


@dataclass(frozen=True, slots=True)
class CatalogPolicy:
    """Allowlist policy for metadata reads."""

    max_classification: Classification = Classification.INTERNAL
    allowed_source_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_classification, Classification):
            raise ValueError("max_classification must be a Classification")
        if self.allowed_source_ids is not None:
            object.__setattr__(
                self, "allowed_source_ids", frozenset(self.allowed_source_ids)
            )

    def allows_source(self, source: DataSourceMetadata) -> bool:
        return (
            source.classification <= self.max_classification
            and (
                self.allowed_source_ids is None
                or source.source_id in self.allowed_source_ids
            )
        )

    def allows_table(self, table: TableMetadata) -> bool:
        return table.classification <= self.max_classification

    def allows_column(self, column: ColumnMetadata) -> bool:
        return column.classification <= self.max_classification


class InMemorySemanticCatalog:
    """Tenant-isolated catalog used as a connector-free reference implementation."""

    def __init__(self, sources: Iterable[DataSourceMetadata] = ()) -> None:
        self._sources: dict[tuple[str, str], DataSourceMetadata] = {}
        for source in sources:
            self.register(source)

    def register(self, source: DataSourceMetadata) -> None:
        key = (source.tenant_id, source.source_id)
        if key in self._sources:
            raise CatalogConflict("source_id is already registered for this tenant")
        self._sources[key] = source

    def read(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[DataSourceMetadata, ...]:
        active_policy = policy or CatalogPolicy()
        return tuple(
            self._filter_source(source, active_policy)
            for (tenant_id, _), source in self._sources.items()
            if tenant_id == principal.org_id and active_policy.allows_source(source)
        )

    def get_source(
        self,
        principal: Principal,
        source_id: str,
        policy: CatalogPolicy | None = None,
    ) -> DataSourceMetadata:
        source = self._sources.get((principal.org_id, source_id))
        if source is None:
            if any(identifier == source_id for _, identifier in self._sources):
                raise CatalogScopeError("source is not available to this tenant")
            raise KeyError(source_id)
        active_policy = policy or CatalogPolicy()
        if not active_policy.allows_source(source):
            raise CatalogScopeError("source is not available under this policy")
        return self._filter_source(source, active_policy)

    @staticmethod
    def _filter_source(
        source: DataSourceMetadata, policy: CatalogPolicy
    ) -> DataSourceMetadata:
        tables = tuple(
            replace(
                table,
                columns=tuple(
                    column
                    for column in table.columns
                    if policy.allows_column(column)
                ),
            )
            for table in source.tables
            if policy.allows_table(table)
        )
        return replace(source, tables=tables)
