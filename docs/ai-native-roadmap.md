# AI-Native Platform Roadmap

**Status:** Proposed
**Decision gate:** Begin only after the target architecture is approved
**Last reviewed:** 2026-11-25

## Phase 0 — Architecture agreement and invariants

Define and approve:

- principal, delegation, task, plan, step, capability, memory, artifact, and
  ledger contracts;
- autonomy levels and approval thresholds;
- policy decision semantics;
- data classification and retention;
- supported connectors;
- non-negotiable execution and tenant-isolation invariants.

**Exit:** approved architecture, threat model, and decision record.

## Phase 1 — Extract the deterministic security kernel

Extract and harden:

- trusted principal validation;
- tenant/database resolution;
- policy interfaces;
- SQL AST safety;
- row restrictions and masking;
- read-only execution;
- quotas, limits, timeouts, and cancellation;
- audit events and incident controls.

Make the kernel transport-independent and cover it with contract and security
tests. Existing GraphQL behavior should be used as a compatibility oracle.

**Exit:** old and new access paths produce equivalent authorization and
execution decisions.

## Phase 2 — Build control-plane primitives

Implement:

- durable task state;
- plan/step state machines;
- capability registry;
- delegation tokens;
- policy decision service;
- approval service;
- memory service;
- governance ledger;
- event bus;
- leases, retries, idempotency, cancellation, and checkpoints.

**Exit:** a non-AI multi-step workflow can execute governed capabilities
durably and recover after interruption.

## Phase 3 — Build the semantic data plane

Add:

- metadata ingestion;
- policy-filtered catalog views;
- entities, relationships, and business metrics;
- lineage;
- embeddings and retrieval;
- freshness and quality metadata;
- provenance for every catalog fact.

**Exit:** agents receive only tenant-authorized and classification-compatible
context.

## Phase 4 — Introduce autonomous read workflows

Start with read-only workflows:

```text
goal
→ discover data
→ create typed plan
→ evaluate policy
→ execute through kernel
→ critique results
→ produce evidence-backed report
```

Add confidence, citations, query hashes, budgets, and reproducible task traces.

**Exit:** L2/L3 read-only workflows complete without direct SQL or credential
access.

## Phase 5 — Rebuild the product experience

Replace the SQL-first dashboard with:

- goal-oriented workspaces;
- live plan and execution timelines;
- evidence and provenance panels;
- approval inbox;
- policy explanations;
- saved workflows;
- tenant-scoped organizational memory;
- governed reports and exports.

Retain expert SQL as a capability-backed mode.

**Exit:** users can complete the primary analytical workflows without authoring
SQL while retaining expert control.

## Phase 6 — Enterprise and operational maturity

Add:

- enterprise OIDC/SAML and SCIM;
- just-in-time access;
- delegated service agents;
- MCP-compatible capability adapters;
- multi-source connectors;
- scheduled workflows;
- operational agents;
- immutable external audit retention;
- model/provider routing;
- trajectory and prompt-injection evaluation gates;
- capacity testing, dashboards, alerts, backup/restore drills, and formal
  security sign-off.

**Exit:** production launch criteria are satisfied for defined autonomy levels.

## Phase 7 — Controlled expansion beyond read-only

Only after read-only autonomy is proven, consider governed transformations or
write actions. These require separate capabilities, policies, approvals,
transaction boundaries, compensating actions, and stronger audit.

Writes must never be enabled by simply relaxing the SELECT-only validator.

## Release gates for every phase

- tenant isolation tests pass;
- policy failures remain fail-closed;
- no capability bypasses the execution kernel;
- sensitive data classification and retention are explicit;
- audit events are attributable and replayable;
- adversarial prompt-injection and tool-abuse tests pass;
- resource budgets are enforced;
- rollback and cancellation behavior is verified.

## Open decisions

- Which initial data sources are in scope?
- Which model providers and deployment modes are acceptable?
- What data classifications require human approval?
- Which capabilities are allowed at L2 versus L3?
- What is the required audit retention and external immutable sink?
- Which workflows define the first product release?
