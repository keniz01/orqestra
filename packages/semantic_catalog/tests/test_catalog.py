from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from execution_kernel import Principal
from semantic_catalog import (
    CatalogPolicy,
    CatalogScopeError,
    Classification,
    ColumnMetadata,
    DataSourceMetadata,
    Freshness,
    InMemorySemanticCatalog,
    Provenance,
    SourceKind,
    TableMetadata,
)


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def principal(org_id: str) -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def source(tenant_id: str = "org-1", source_id: str = "warehouse") -> DataSourceMetadata:
    return DataSourceMetadata(
        tenant_id=tenant_id,
        source_id=source_id,
        name="Warehouse",
        kind=SourceKind.WAREHOUSE,
        classification=Classification.PUBLIC,
        provenance=Provenance("scanner", "warehouse", NOW, "catalog-job"),
        freshness=Freshness(NOW, timedelta(hours=1)),
        tables=(
            TableMetadata(
                tenant_id=tenant_id,
                source_id=source_id,
                table_id="customers",
                name="Customers",
                classification=Classification.PUBLIC,
                columns=(
                    ColumnMetadata(
                        tenant_id=tenant_id,
                        source_id=source_id,
                        table_id="customers",
                        name="email",
                        data_type="text",
                        classification=Classification.CONFIDENTIAL,
                    ),
                    ColumnMetadata(
                        tenant_id=tenant_id,
                        source_id=source_id,
                        table_id="customers",
                        name="id",
                        data_type="uuid",
                        classification=Classification.PUBLIC,
                    ),
                ),
            ),
        ),
    )


def test_reads_are_tenant_isolated_and_policy_filtered():
    catalog = InMemorySemanticCatalog((source(), source("org-2", "other")))

    visible = catalog.read(
        principal("org-1"),
        CatalogPolicy(max_classification=Classification.PUBLIC),
    )

    assert [item.source_id for item in visible] == ["warehouse"]
    assert [column.name for column in visible[0].tables[0].columns] == ["id"]
    assert catalog.read(principal("org-2"))[0].source_id == "other"


def test_cross_tenant_source_access_never_leaks_metadata():
    catalog = InMemorySemanticCatalog((source(),))

    with pytest.raises(CatalogScopeError):
        catalog.get_source(principal("org-2"), "warehouse")

    assert catalog.read(principal("org-2")) == ()


def test_provenance_and_freshness_require_valid_values():
    with pytest.raises(ValueError, match="timezone"):
        Provenance("scanner", "warehouse", datetime(2026, 1, 1), "job")
    with pytest.raises(ValueError, match="max_age"):
        Freshness(NOW, timedelta(0))
    with pytest.raises(ValueError, match="timezone"):
        Freshness(datetime(2026, 1, 1), timedelta(hours=1))


def test_policy_can_hide_a_source_by_classification():
    restricted = DataSourceMetadata(
        tenant_id="org-1",
        source_id="secret",
        name="Secret",
        kind=SourceKind.DATABASE,
        classification=Classification.RESTRICTED,
    )
    catalog = InMemorySemanticCatalog((source(), restricted))

    assert [item.source_id for item in catalog.read(principal("org-1"))] == ["warehouse"]
