# Phase 4 read workflow contracts

Read workflows are bounded, model-independent intent contracts. A planner
produces a goal and typed capability steps; it does not receive credentials or
executable SQL. A runner consumes only results injected by an already-governed
capability adapter. The in-memory runner is a reference implementation and
does not execute, authorize, or discover capabilities.

Each successful result includes provenance evidence and a confidence score in
the range `0..1`. Missing evidence or confidence prevents completion. Direct
SQL and credential-shaped inputs are rejected at the plan boundary.

The Phase 4 reference implementation also enforces per-plan step and evidence
budgets, carries query hashes and citation references through capability
results, reviews successful results through a structured critic boundary, and
exposes an evidence-backed report keyed by the durable task trace identifier.
The runner and report contracts remain model-independent; capability
authorization and execution stay outside this package.

The complete reference path is:

1. assemble tenant-filtered context;
2. produce typed intent from a deterministic planner;
3. materialize server-owned read queries through a capability adapter;
4. enforce policy, tenant binding, read-only SQL validation, and kernel budgets;
5. critique results and allow only bounded, non-broadening replans; and
6. persist a tenant-scoped report keyed by the durable task trace.

The Phase 4 exit proof covers successful governed reads, policy denial,
cross-tenant context rejection, direct SQL and credential rejection, budget
limits, provenance requirements, and report replay isolation.
