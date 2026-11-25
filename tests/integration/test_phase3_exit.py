from __future__ import annotations

from datetime import datetime, timedelta, timezone

from execution_kernel import Principal
from governance import InMemoryGovernanceLedger
from memory_service import (
    InMemoryMemoryStore,
    MemoryClassification,
    MemoryProvenance,
    MemoryRecord,
    MemoryRetention,
    MemoryScope,
    RetentionClass,
)
from read_workflows import ContextAssembler, ContextPolicy
from semantic_catalog import (
    CatalogPolicy,
    Classification,
    ColumnMetadata,
    DataSourceMetadata,
    Freshness,
    MetadataIngestionService,
    Provenance,
    SQLiteEmbeddingIndex,
    SQLiteSemanticCatalog,
    SourceKind,
    TableMetadata,
)


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def principal(org_id: str) -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def provenance(object_name: str) -> Provenance:
    return Provenance("metadata-scanner", object_name, NOW, "phase3-test")


def source(tenant_id: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        tenant_id=tenant_id,
        source_id="warehouse",
        name="Warehouse",
        kind=SourceKind.WAREHOUSE,
        classification=Classification.INTERNAL,
        provenance=provenance("warehouse"),
        freshness=Freshness(NOW, timedelta(hours=1)),
        tables=(
            TableMetadata(
                tenant_id=tenant_id,
                source_id="warehouse",
                table_id="orders",
                name="Orders",
                classification=Classification.INTERNAL,
                provenance=provenance("warehouse.orders"),
                columns=(
                    ColumnMetadata(
                        tenant_id=tenant_id,
                        source_id="warehouse",
                        table_id="orders",
                        name="order_id",
                        data_type="uuid",
                        classification=Classification.PUBLIC,
                        provenance=provenance("warehouse.orders.order_id"),
                    ),
                    ColumnMetadata(
                        tenant_id=tenant_id,
                        source_id="warehouse",
                        table_id="orders",
                        name="customer_email",
                        data_type="text",
                        classification=Classification.CONFIDENTIAL,
                        provenance=provenance("warehouse.orders.customer_email"),
                    ),
                ),
            ),
        ),
    )


def memory(org_id: str) -> MemoryRecord:
    return MemoryRecord(
        org_id=org_id,
        scope=MemoryScope.TENANT,
        scope_id="tenant",
        content="orders are refreshed hourly",
        classification=MemoryClassification.INTERNAL,
        retention=MemoryRetention(RetentionClass.STANDARD),
        provenance=MemoryProvenance("catalog", "orders", "user-1", "verified"),
    )


def test_phase3_exit_delivers_authorized_context_only():
    catalog = SQLiteSemanticCatalog(":memory:")
    ledger = InMemoryGovernanceLedger()
    ingestion = MetadataIngestionService(catalog, ledger)
    ingestion.ingest(
        principal("org-1"),
        type("Collector", (), {"collect": lambda self, _: (source("org-1"),)})(),
    )
    ingestion.ingest(
        principal("org-2"),
        type("Collector", (), {"collect": lambda self, _: (source("org-2"),)})(),
    )

    memory_store = InMemoryMemoryStore()
    memory_store.write(principal("org-1"), memory("org-1"))
    memory_store.write(principal("org-2"), memory("org-2"))
    context = ContextAssembler(catalog, memory_store).assemble(
        principal("org-1"),
        ContextPolicy(
            catalog=CatalogPolicy(max_classification=Classification.PUBLIC),
            max_memory_classification=MemoryClassification.PUBLIC,
        ),
    )

    assert context.tenant_id == "org-1"
    assert [item.source_id for item in context.catalog] == []
    assert context.memories == ()
    assert len(ledger.events_for(principal("org-1"))) == 1
    assert len(ledger.events_for(principal("org-2"))) == 1


def test_phase3_exit_retrieval_keeps_tenant_and_classification_filters():
    index = SQLiteEmbeddingIndex(":memory:")
    index.index(principal("org-1"), "orders", "orders customer email", Classification.INTERNAL)
    index.index(principal("org-1"), "public-orders", "orders identifiers", Classification.PUBLIC)
    index.index(principal("org-2"), "other", "orders customer email", Classification.PUBLIC)

    results = index.search(
        principal("org-1"),
        "customer email",
        policy=CatalogPolicy(max_classification=Classification.PUBLIC),
    )

    assert [item[0] for item in results] == ["public-orders"]
