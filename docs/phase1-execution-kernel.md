# Phase 1 — Execution Kernel Foundation

**Status:** Hardened kernel contracts implemented; transport compatibility remains
**Branch:** `feat/execution-kernel-foundation`

This phase introduces a transport-independent, deterministic kernel for
governed read execution. It is intentionally independent of HTTP, GraphQL,
agent models, and database credentials.

## Implemented

- immutable trusted `Principal` contract;
- explicit capability registry with read-only capability metadata;
- time-bounded agent delegation scoped to capabilities and tasks;
- server-owned `(org_id, database_id)` tenant binding resolution;
- deny-by-default capability policy evaluator;
- typed `QueryPlan` and bounded `QueryResult` contracts;
- deterministic `sqlglot` validation for one read-only SELECT/WITH statement;
- rejection of mutations, comments, multiple statements, forbidden functions,
  system tables, empty input, control characters, and oversized input;
- policy-driven result masking;
- maximum-row bounding with truncation reporting;
- maximum-result-byte bounding with truncation reporting;
- append-only audit events for tenant denial, SQL denial, policy decisions, and
  successful capability execution;
- executor protocol that keeps database I/O outside the kernel;
- explicit cancellation and timeout context for cancellable connector adapters;
- delegated task identity consistency checks;
- focused tests for authorization, tenant isolation, SQL rejection, masking,
  result bounds, cancellation, timeout, and delegated task scope.

## Explicit non-goals for this slice

- no HTTP or GraphQL transport;
- no model or agent runtime;
- no database connector implementation;
- no credential loading;
- no production OPA adapter;
- no durable task store or distributed quota coordinator.

Those capabilities are subsequent phases. The kernel contracts are designed so
they can be used by those adapters without allowing them to bypass validation,
policy, tenant resolution, masking, limits, or audit.

## Validation

```text
python3 -m pytest -q
11 passed
```

Legacy synchronous executors remain supported for compatibility. Production
connectors must implement the cancellable execution context so they can enforce
the deadline and observe cancellation while database I/O is in progress.
