from __future__ import annotations

import sqlite3

from execution_kernel import Principal
from semantic_catalog import (
    BusinessMetric,
    CatalogPolicy,
    Classification,
    LineageEdge,
    SemanticEntity,
    SemanticRelationship,
    SQLiteSemanticFacts,
)


def principal(org_id: str) -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def test_semantic_facts_are_durable_and_policy_filtered():
    connection = sqlite3.connect(":memory:")
    facts = SQLiteSemanticFacts(connection)
    facts.put_entity(SemanticEntity("org-1", "customer", "Customer", classification=Classification.PUBLIC))
    facts.put_entity(SemanticEntity("org-2", "customer", "Other", classification=Classification.PUBLIC))
    facts.put_relationship(
        SemanticRelationship("org-1", "customer-orders", "customer", "order", "owns")
    )
    facts.put_metric(BusinessMetric("org-1", "revenue", "Revenue", "sum(order.total)"))
    facts.put_lineage(LineageEdge("org-1", "orders-to-revenue", "orders.total", "revenue"))

    assert [item.name for item in facts.read_entities(principal("org-1"))] == ["Customer"]
    assert facts.read_entities(principal("org-2"))[0].tenant_id == "org-2"
    assert facts.read_relationships(principal("org-1"))[0].relationship_type == "owns"
    assert facts.read_metrics(principal("org-1"))[0].metric_id == "revenue"
    assert facts.read_lineage(principal("org-1"))[0].downstream == "revenue"

    facts.put_entity(
        SemanticEntity("org-1", "secret", "Secret", classification=Classification.RESTRICTED)
    )
    assert facts.read_entities(
        principal("org-1"),
        CatalogPolicy(max_classification=Classification.PUBLIC),
    )[0].entity_id == "customer"
