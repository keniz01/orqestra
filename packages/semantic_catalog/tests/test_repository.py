from __future__ import annotations

import sqlite3

import pytest
from execution_kernel import Principal
from semantic_catalog import (
    CatalogPolicy,
    CatalogScopeError,
    Classification,
    DataSourceMetadata,
    MetadataIngestionService,
    SQLiteSemanticCatalog,
    SourceKind,
)


def principal(org_id: str) -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def source(tenant_id: str, source_id: str = "warehouse") -> DataSourceMetadata:
    return DataSourceMetadata(
        tenant_id=tenant_id,
        source_id=source_id,
        name=source_id,
        kind=SourceKind.WAREHOUSE,
        classification=Classification.PUBLIC,
    )


def test_sqlite_catalog_survives_restart_and_filters_by_tenant():
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteSemanticCatalog(connection)
    catalog.upsert(source("org-1"))
    catalog.upsert(source("org-2", "other"))

    assert [item.source_id for item in catalog.read(principal("org-1"))] == ["warehouse"]
    assert catalog.read(principal("org-2"))[0].source_id == "other"

    restarted = SQLiteSemanticCatalog(connection)
    assert restarted.get_source(principal("org-1"), "warehouse").tenant_id == "org-1"


def test_sqlite_catalog_preserves_policy_filtering():
    catalog = SQLiteSemanticCatalog(":memory:")
    catalog.upsert(
        DataSourceMetadata(
            tenant_id="org-1",
            source_id="secret",
            name="secret",
            kind=SourceKind.DATABASE,
            classification=Classification.RESTRICTED,
        )
    )

    assert catalog.read(
        principal("org-1"),
        CatalogPolicy(max_classification=Classification.PUBLIC),
    ) == ()
    with pytest.raises(CatalogScopeError):
        catalog.get_source(
            principal("org-1"),
            "secret",
            CatalogPolicy(max_classification=Classification.PUBLIC),
        )


def test_ingestion_rejects_cross_tenant_collector_output():
    class Collector:
        def collect(self, principal: Principal):
            return (source("other"),)

    with pytest.raises(CatalogScopeError):
        MetadataIngestionService(SQLiteSemanticCatalog(":memory:")).ingest(
            principal("org-1"), Collector()
        )
