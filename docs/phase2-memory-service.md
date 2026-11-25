# Phase 2 — Memory service foundation

The memory service stores typed, tenant-scoped records for bounded context
retrieval. Every record carries a scope, classification, retention policy, and
provenance. The reference implementation is in-memory and intentionally has no
embedding or model-provider dependency.

Writes and reads require a trusted `Principal`. The authorization boundary
first requires the principal's organization to match the record; tenant-scoped
records are then available within that organization, while user- and
task-scoped records require the owning principal. Retrieval has an explicit
maximum and excludes expired records.

`InMemoryMemoryStore` is a contract-test and local-development implementation,
not a durable persistence layer. A production adapter must preserve the same
tenant isolation, authorization, metadata validation, retention, and bounded
retrieval invariants.
