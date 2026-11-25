# Phase 3: Semantic Catalog Foundation

The semantic catalog is a tenant-scoped metadata boundary, not a connector or
retrieval implementation. Its typed contracts describe data sources, tables,
columns, classification, freshness expectations, and provenance.

`InMemorySemanticCatalog` is the reference implementation for this phase. A
read is always scoped from the trusted `Principal.org_id`; a
`CatalogPolicy` then filters source, table, and column metadata by classification
and optional source allowlist. Records from another tenant are never returned,
even when identifiers overlap.

The implementation deliberately has no embeddings, connectors, or database
access. Future adapters must preserve the same tenant and policy-filtering
contract before metadata reaches an agent or execution planner.
