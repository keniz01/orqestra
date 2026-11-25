from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from execution_kernel import Principal
from memory_service import (
    InMemoryMemoryStore,
    MemoryClassification,
    MemoryProvenance,
    MemoryRecord,
    MemoryRetention,
    MemoryScope,
    RetentionClass,
)
from read_workflows import (
    ContextAssembler,
    ContextPolicy,
    ContextScopeError,
)
from semantic_catalog import (
    CatalogPolicy,
    Classification,
    DataSourceMetadata,
    InMemorySemanticCatalog,
    Provenance,
    SourceKind,
)


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def principal(org_id: str = "org-1") -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def source(org_id: str, source_id: str, classification: Classification) -> DataSourceMetadata:
    return DataSourceMetadata(
        tenant_id=org_id,
        source_id=source_id,
        name=source_id,
        kind=SourceKind.WAREHOUSE,
        classification=classification,
        provenance=Provenance("scanner", source_id, NOW, "catalog-job"),
    )


def memory(
    *,
    org_id: str = "org-1",
    classification: MemoryClassification = MemoryClassification.INTERNAL,
    retention: MemoryRetention | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        org_id=org_id,
        scope=MemoryScope.TENANT,
        scope_id="tenant",
        content="verified context",
        classification=classification,
        retention=retention or MemoryRetention(RetentionClass.STANDARD),
        provenance=MemoryProvenance("test", "record-1", "user-1", "verified"),
    )


def test_assembler_keeps_catalog_and_memory_tenant_isolated():
    catalog = InMemorySemanticCatalog(
        (source("org-1", "orders", Classification.PUBLIC), source("org-2", "secret", Classification.PUBLIC))
    )
    store = InMemoryMemoryStore()
    visible = store.write(principal(), memory())
    store.write(principal("org-2"), memory(org_id="org-2"))

    context = ContextAssembler(catalog, store).assemble(principal())

    assert context.tenant_id == "org-1"
    assert [item.source_id for item in context.catalog] == ["orders"]
    assert context.memories == (visible,)


def test_assembler_rejects_cross_tenant_context_from_a_reader():
    class LeakingCatalog:
        def read(self, principal: Principal, policy: CatalogPolicy):
            return (source("org-2", "wrong-tenant", Classification.PUBLIC),)

    with pytest.raises(ContextScopeError):
        ContextAssembler(LeakingCatalog(), InMemoryMemoryStore()).assemble(principal())


def test_assembler_filters_classification_and_preserves_provenance():
    catalog_source = source("org-1", "orders", Classification.PUBLIC)
    store = InMemoryMemoryStore()
    allowed = store.write(principal(), memory(classification=MemoryClassification.PUBLIC))
    store.write(principal(), memory(classification=MemoryClassification.CONFIDENTIAL))

    context = ContextAssembler(
        InMemorySemanticCatalog((catalog_source,)),
        store,
    ).assemble(
        principal(),
        ContextPolicy(
            catalog=CatalogPolicy(max_classification=Classification.PUBLIC),
            max_memory_classification=MemoryClassification.PUBLIC,
        ),
    )

    assert context.catalog[0].provenance == catalog_source.provenance
    assert context.memories == (allowed,)
    assert context.memories[0].provenance.source == "test"


def test_assembler_excludes_expired_memory_and_bounds_context():
    store = InMemoryMemoryStore()
    current = store.write(principal(), memory())
    expired = store.write(
        principal(),
        memory(
            retention=MemoryRetention(
                RetentionClass.TASK,
                datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        ),
    )
    catalog = InMemorySemanticCatalog(
        tuple(source("org-1", f"source-{index}", Classification.PUBLIC) for index in range(3))
    )

    context = ContextAssembler(catalog, store).assemble(
        principal(),
        ContextPolicy(catalog_limit=1, memory_limit=1, total_limit=2),
    )

    assert context.size == 2
    assert len(context.catalog) == 1
    assert context.memories == (current,)
    assert expired.memory_id not in {item.memory_id for item in context.memories}
