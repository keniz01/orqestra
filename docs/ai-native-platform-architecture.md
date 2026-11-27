# Target AI-Native Platform Architecture

**Status:** Approved for implementation
**Decision gate:** Phase 5 product implementation
**Last reviewed:** 2026-11-27

## Product definition

The product becomes an autonomous, policy-governed data operating system. Users
state goals, define constraints, approve risk, inspect evidence, and receive
reproducible outputs. They are not required to author SQL or manage individual
API calls, although an expert SQL workspace remains available as a governed
capability.

## Architectural principle

> Agents may reason freely, but they may execute only typed, policy-authorized
> capabilities through deterministic control-plane services.

No agent receives database credentials. No agent executes arbitrary SQL
directly. Every action is represented as a typed intent, evaluated against
identity, tenant, policy, risk, budget, and approval state.

## Logical architecture

```text
                    ┌──────────────────────────────┐
                    │        Experience Plane       │
                    │ workspaces · dashboards · API  │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       Intent & Task Plane     │
                    │ goals · tasks · plans · state  │
                    └──────────────┬───────────────┘
                                   │
       ┌───────────────────────────▼───────────────────────────┐
       │                    Agent Runtime                        │
       │ planner · specialists · critics · memory/context         │
       │ checkpointing · retries · cancellation · recovery        │
       └───────────────┬──────────────┬──────────────┬──────────┘
                       │              │              │
          ┌────────────▼──────┐ ┌─────▼────────┐ ┌───▼────────────┐
          │ Capability Registry│ │ Policy Plane │ │ Approval Plane │
          │ typed tools/actions │ │ risk/budgets │ │ JIT / human    │
          └────────────┬──────┘ └─────┬────────┘ └───┬────────────┘
                       │              │              │
       ┌───────────────▼──────────────▼──────────────▼────────────┐
       │                    Execution Kernel                       │
       │ query compiler · connector broker · masking · quotas      │
       │ cancellation · read-only execution · audit                │
       └───────────────┬──────────────────────────┬────────────────┘
                       │                          │
          ┌────────────▼──────────┐    ┌──────────▼─────────────┐
          │ Semantic Data Plane    │    │ Governed Data Sources   │
          │ catalog · lineage      │    │ PostgreSQL · SQLite     │
          │ metrics · embeddings   │    │ warehouses · APIs/files │
          └───────────────────────┘    └────────────────────────┘
```

## Core platform planes

### Identity and delegation plane

Represent human, service, agent, and delegated-task identities separately.
Every agent action must retain this chain:

```text
human principal → delegated task → agent instance → capability invocation
```

Delegation tokens should be scoped by tenant, task, capability, data
classification, expiry, budget, and approval state.

### Intent and task plane

Replace isolated requests with durable state:

```text
goal → task → plan → step → capability call → result → decision → checkpoint
```

Tasks must support pause/resume, deadlines, cancellation, retry policy,
approval waits, partial results, recovery, replay, and human takeover.

### Agent runtime

Use specialized, replaceable agents:

- planner;
- schema and semantic discovery agent;
- analyst agent;
- query-planning agent;
- policy critic;
- result critic;
- report/artifact agent;
- operations agent;
- approval coordinator.

Agents should emit structured decisions and plans, not unbounded executable
commands.

### Capability registry

Every executable operation is registered with:

- typed input and output schemas;
- required permissions;
- tenant scope;
- data classifications;
- risk level;
- side-effect classification;
- budget requirements;
- approval requirements;
- timeout and resource limits;
- audit event definition;
- implementation adapter.

Examples include `catalog.inspect_schema`,
`catalog.search_semantic_metadata`, `data.plan_read_query`,
`data.execute_read_query`, `data.export_result`,
`analysis.profile_dataset`, `analysis.detect_anomalies`,
`report.create_artifact`, and `workflow.request_approval`.

### Policy and risk plane

OPA should become the policy decision point for all capabilities, not only
SQL. Decisions should support:

```text
allow | deny | allow_with_constraints | require_approval
```

Inputs include principal/delegation, tenant, workspace, purpose, capability,
tables, columns, classifications, result size, destination, model/provider,
budget, approval state, time, and risk signals.

Constraints can require row filters, masking, maximum rows/bytes, destination
allowlists, model restrictions, retention, step-up authentication, or no
export/persistence.

### Semantic data plane

The current schema introspection and embeddings become a governed semantic
catalog containing schema metadata, relationships, business entities, metrics,
descriptions, synonyms, classifications, ownership, lineage, freshness,
quality signals, examples, and retrieval embeddings.

Retrieval must be authorization-filtered before context reaches an agent.

### Deterministic execution kernel

The execution kernel owns:

1. trusted principal validation;
2. tenant/database resolution;
3. capability authorization;
4. typed query compilation;
5. AST-level row and column enforcement;
6. read-only database execution;
7. quotas, limits, timeouts, and cancellation;
8. result masking;
9. audit and provenance.

The agent runtime must never bypass this kernel.

### Memory and context plane

Separate memory by trust, scope, and retention:

- ephemeral task context;
- task plans, checkpoints, and observations;
- user preferences;
- tenant business definitions and ontology;
- system policies, capabilities, runbooks, and evaluations.

Every memory record requires owner, tenant/workspace scope, classification,
retention, provenance, access policy, encryption, and deletion semantics.
Sensitive query results must not automatically become long-term memory.

### Governance ledger

The existing audit chain should become an append-only ledger recording
identity, task and plan versions, model/provider/version, prompt/template
identifiers, retrieved context references, capability calls, policy decisions,
approvals, generated plans, SQL hashes, result/artifact hashes, masking,
retries, failures, and cancellations.

## Safety invariants

- No agent receives raw database credentials.
- No request or agent may bypass tenant resolution.
- No data access bypasses policy evaluation.
- Only typed query plans reach the SQL compiler.
- Only read-only database roles are used for analytical execution.
- Row restrictions and masking occur before data leaves the execution kernel.
- Policy outages deny access.
- Agent retries cannot increase authority or budgets.
- Long-term memory is policy-controlled and tenant-scoped.
- Every autonomous action is attributable and replayable.

## Initial autonomy boundary

The first target should be L2/L3 read-only autonomy:

```text
L0 Manual       user invokes capabilities
L1 Assisted     agent proposes; user executes
L2 Governed     agent executes low-risk read workflows
L3 Conditional  agent executes within policy and approval bounds
L4 Scheduled    recurring workflows with monitoring
L5 Autonomous   adaptive execution within strict bounds
```

Writes and external side effects are explicitly out of scope until the
read-only platform has proven governance, evaluation, recovery, and audit.
