from __future__ import annotations

from datetime import datetime, timezone

import pytest
from execution_kernel import Principal
from governance import InMemoryGovernanceLedger
from semantic_catalog import (
    DataSourceMetadata,
    MetadataIngestionService,
    Provenance,
    SQLiteSemanticCatalog,
    SourceKind,
)


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def principal() -> Principal:
    return Principal(user_id="user-1", org_id="org-1")


def test_ingestion_requires_provenance_and_records_safe_governance_event():
    source = DataSourceMetadata(
        tenant_id="org-1",
        source_id="warehouse",
        name="Warehouse",
        kind=SourceKind.WAREHOUSE,
        provenance=Provenance("scanner", "warehouse", NOW, "catalog-job"),
    )
    ledger = InMemoryGovernanceLedger()
    repository = SQLiteSemanticCatalog(":memory:")

    MetadataIngestionService(repository, ledger).ingest(
        principal(),
        type("Collector", (), {"collect": lambda self, _: (source,)})(),
    )

    events = ledger.events_for(principal())
    assert len(events) == 1
    assert events[0].event_type == "catalog.ingested"
    assert events[0].payload == {
        "collector": "catalog-job",
        "source_id": "warehouse",
        "source_kind": "warehouse",
        "source_object": "warehouse",
        "source_system": "scanner",
    }


def test_ingestion_rejects_source_without_provenance():
    source = DataSourceMetadata(
        tenant_id="org-1",
        source_id="warehouse",
        name="Warehouse",
        kind=SourceKind.WAREHOUSE,
    )

    with pytest.raises(ValueError, match="provenance"):
        MetadataIngestionService(SQLiteSemanticCatalog(":memory:")).ingest(
            principal(),
            type("Collector", (), {"collect": lambda self, _: (source,)})(),
        )
