# Phase 3: Semantic Catalog Foundation

The semantic catalog is a tenant-scoped metadata boundary, not a connector or
retrieval implementation. Its typed contracts describe data sources, tables,
columns, classification, freshness expectations, and provenance.

`InMemorySemanticCatalog` is the reference implementation for this phase.
`SQLiteSemanticCatalog` provides the durable adapter, and
`MetadataIngestionService` is the connector-neutral ingestion boundary. A read
is always scoped from the trusted `Principal.org_id`; a
`CatalogPolicy` then filters source, table, and column metadata by classification
and optional source allowlist. Records from another tenant are never returned,
even when identifiers overlap.

Semantic entities, relationships, business metrics, lineage, quality metadata,
and tenant-filtered retrieval are exposed through separate contracts. Ingestion
requires provenance on every source fact and can append a safe
`catalog.ingested` governance event containing identifiers only. Adapters must
preserve the same tenant and policy-filtering contract before metadata reaches
an agent or execution planner.
