"""Tenant-scoped context assembly for governed read workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from execution_kernel import Principal
from memory_service import (
    InMemoryMemoryStore,
    MemoryClassification,
    MemoryRecord,
)
from semantic_catalog import (
    CatalogPolicy,
    Classification,
    DataSourceMetadata,
    InMemorySemanticCatalog,
)


class ContextScopeError(PermissionError):
    """Raised when a context source violates the requested tenant boundary."""


class CatalogReader(Protocol):
    def read(
        self, principal: Principal, policy: CatalogPolicy | None = None
    ) -> tuple[DataSourceMetadata, ...]:
        ...


class MemoryReader(Protocol):
    def retrieve(
        self,
        principal: Principal,
        *,
        classification: MemoryClassification | None = None,
        limit: int = 10,
    ) -> tuple[MemoryRecord, ...]:
        ...


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """Allowlist and limits applied before context reaches a workflow."""

    catalog: CatalogPolicy = CatalogPolicy()
    max_memory_classification: MemoryClassification = MemoryClassification.INTERNAL
    catalog_limit: int = 10
    memory_limit: int = 10
    total_limit: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, CatalogPolicy):
            raise ValueError("catalog must be a CatalogPolicy")
        if not isinstance(self.max_memory_classification, MemoryClassification):
            raise ValueError(
                "max_memory_classification must be a MemoryClassification"
            )
        if self.catalog_limit < 1:
            raise ValueError("catalog_limit must be positive")
        if self.memory_limit < 1:
            raise ValueError("memory_limit must be positive")
        if self.total_limit < 1:
            raise ValueError("total_limit must be positive")


@dataclass(frozen=True, slots=True)
class GovernedContext:
    """The bounded, already-filtered context supplied to a read workflow."""

    tenant_id: str
    catalog: tuple[DataSourceMetadata, ...] = ()
    memories: tuple[MemoryRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        object.__setattr__(self, "catalog", tuple(self.catalog))
        object.__setattr__(self, "memories", tuple(self.memories))
        if any(source.tenant_id != self.tenant_id for source in self.catalog):
            raise ContextScopeError("catalog context crossed the tenant boundary")
        if any(memory.org_id != self.tenant_id for memory in self.memories):
            raise ContextScopeError("memory context crossed the tenant boundary")

    @property
    def size(self) -> int:
        return len(self.catalog) + len(self.memories)


_MEMORY_CLASSIFICATION_RANK = {
    MemoryClassification.PUBLIC: 0,
    MemoryClassification.INTERNAL: 1,
    MemoryClassification.CONFIDENTIAL: 2,
    MemoryClassification.RESTRICTED: 3,
}


class ContextAssembler:
    """Retrieve policy-filtered catalog facts and authorized memory records."""

    def __init__(
        self,
        catalog: CatalogReader | InMemorySemanticCatalog,
        memory: MemoryReader | InMemoryMemoryStore,
    ) -> None:
        self._catalog = catalog
        self._memory = memory

    def assemble(
        self,
        principal: Principal,
        policy: ContextPolicy | None = None,
    ) -> GovernedContext:
        active_policy = policy or ContextPolicy()
        catalog = self._catalog.read(principal, active_policy.catalog)
        if any(source.tenant_id != principal.org_id for source in catalog):
            raise ContextScopeError("catalog context crossed the tenant boundary")
        catalog = tuple(catalog[: min(active_policy.catalog_limit, active_policy.total_limit)])
        remaining = max(active_policy.total_limit - len(catalog), 0)
        memories = (
            self._memory.retrieve(
                principal,
                limit=min(active_policy.memory_limit, remaining),
            )
            if remaining
            else ()
        )
        if any(memory.org_id != principal.org_id for memory in memories):
            raise ContextScopeError("memory context crossed the tenant boundary")
        memories = tuple(
            memory
            for memory in memories
            if _MEMORY_CLASSIFICATION_RANK[memory.classification]
            <= _MEMORY_CLASSIFICATION_RANK[active_policy.max_memory_classification]
        )
        return GovernedContext(
            tenant_id=principal.org_id,
            catalog=catalog,
            memories=memories,
        )
