from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from execution_kernel import Principal
from semantic_catalog import (
    CatalogPolicy,
    Classification,
    HashEmbeddingProvider,
    QualityMetadata,
    QualityStatus,
    SQLiteEmbeddingIndex,
)


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def principal(org_id: str) -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def test_quality_metadata_validates_scores_and_timestamps():
    value = QualityMetadata("orders", QualityStatus.PASS, NOW, completeness=0.99)
    assert value.status is QualityStatus.PASS
    with pytest.raises(ValueError, match="between"):
        QualityMetadata("orders", QualityStatus.PASS, NOW, completeness=1.1)
    with pytest.raises(ValueError, match="timezone"):
        QualityMetadata("orders", QualityStatus.PASS, datetime(2026, 1, 1))


def test_retrieval_is_durable_tenant_scoped_and_policy_filtered():
    connection = sqlite3.connect(":memory:")
    index = SQLiteEmbeddingIndex(connection, HashEmbeddingProvider(16))
    index.index(principal("org-1"), "orders", "customer orders revenue", Classification.PUBLIC)
    index.index(principal("org-1"), "secret", "restricted customer revenue", Classification.RESTRICTED)
    index.index(principal("org-2"), "other", "customer orders", Classification.PUBLIC)

    result = index.search(
        principal("org-1"),
        "customer revenue",
        policy=CatalogPolicy(max_classification=Classification.PUBLIC),
    )

    assert result[0][0] == "orders"
    assert "secret" not in {item[0] for item in result}
    assert index.search(principal("org-2"), "customer")[0][0] == "other"
