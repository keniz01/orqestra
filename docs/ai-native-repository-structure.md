# Proposed Greenfield Repository Structure

**Status:** Proposed
**Last reviewed:** 2026-11-25

The target repository should be organized around platform domains and stable
contracts rather than the current service split. Existing services can be
adapted behind compatibility boundaries during migration, but they should not
define the final architecture.

```text
secure-data-platform/
├── apps/
│   ├── experience-web/              # Workspaces, dashboards, approvals
│   ├── control-api/                 # Public API, tasks, sessions, workspaces
│   ├── agent-runtime/               # Planning, workers, checkpoints, recovery
│   ├── execution-kernel/            # Governed deterministic execution
│   ├── policy-service/              # OPA integration and policy bundles
│   ├── catalog-service/             # Semantic metadata and retrieval
│   ├── artifact-service/            # Reports, exports, evidence
│   └── connector-broker/            # Tenant-safe source connections
│
├── packages/
│   ├── identity-contracts/           # Principals and delegation
│   ├── task-contracts/               # Goals, tasks, plans, steps
│   ├── capability-contracts/         # Tools, risk, budgets, approvals
│   ├── query-ir/                    # Typed query intent and relational IR
│   ├── policy-contracts/             # Decisions and constraints
│   ├── catalog-contracts/            # Metadata and provenance
│   ├── audit-contracts/             # Governance ledger events
│   ├── memory-contracts/            # Scope, retention, classification
│   └── telemetry/                   # Correlation and tracing conventions
│
├── domains/
│   ├── identity/
│   ├── authorization/
│   ├── tenancy/
│   ├── semantic-catalog/
│   ├── query-governance/
│   ├── autonomous-workflows/
│   ├── approvals/
│   ├── artifacts/
│   └── incident-response/
│
├── agents/
│   ├── planner/
│   ├── schema-agent/
│   ├── analyst-agent/
│   ├── query-agent/
│   ├── policy-critic/
│   ├── result-critic/
│   ├── report-agent/
│   └── operations-agent/
│
├── infrastructure/
│   ├── docker/
│   ├── kubernetes/
│   ├── terraform/
│   ├── opa/
│   ├── postgres/
│   ├── redis/
│   ├── observability/
│   └── secrets/
│
├── evals/
│   ├── query-generation/
│   ├── schema-retrieval/
│   ├── policy-bypass/
│   ├── tenant-isolation/
│   ├── prompt-injection/
│   ├── agent-trajectories/
│   └── regression/
│
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── security/
│   ├── tenancy/
│   ├── resilience/
│   └── end-to-end/
│
├── docs/
│   ├── architecture/
│   ├── security/
│   ├── capability-catalog/
│   ├── operating-model/
│   └── migration/
│
└── README.md
```

## Design rules

- `packages/` contains versioned contracts with no transport-specific logic.
- `domains/` contains business invariants and domain services.
- `apps/` contains deployable processes and adapters.
- `agents/` contains model-backed behavior and must use registered capabilities.
- `execution-kernel/` remains deterministic and model-independent.
- `evals/` is a first-class release gate, not an optional experiment area.
- Secrets, tenant bindings, and policy bundles remain separate assets.
- Compatibility adapters are temporary and must have explicit removal criteria.
