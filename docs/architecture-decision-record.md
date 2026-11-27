# Architecture Decision Record — Governed Read-Only Platform

**Status:** Approved for implementation
**Approved:** 2026-11-27

This decision record turns the existing secure gateway guarantees into the
initial operating rules for Orqestra.

## Decisions

### Identity and authority

- Auth0/OIDC remains the human identity boundary.
- Tokens are validated server-side; tenant identity comes only from trusted
  claims, never client-supplied headers.
- Roles remain tenant-scoped and deny-by-default, with RBAC and separation of
  duties.
- Agent authority is represented as:

  ```text
  human principal → durable task → agent instance → capability invocation
  ```

- Agents never receive database credentials or direct connector access.

### Initial data sources

- PostgreSQL and SQLite are the first supported governed sources because the
  gateway already proves tenant resolution, read-only execution, SQL safety,
  masking, budgets, and audit for them.
- Additional warehouses, APIs, and file sources must use registered connector
  adapters and the same policy and audit boundaries.

### Model providers

- Model providers are an allowlisted configuration, not an execution
  authority.
- OpenRouter/Gemini-compatible provider adapters may be used initially.
- Models produce typed goals, plans, critiques, and reports; they never
  execute SQL or receive credentials.
- Provider, model version, prompt/template version, and policy decision are
  recorded in the governance trace.
- Restricted data is not sent to an external model unless an explicit policy
  allows it.

### Human approval

- Low-risk, tenant-scoped read workflows run without approval.
- Approval is required for restricted or confidential data, exports, large
  result sets, persistent artifacts, unusual access patterns, or any
  capability whose policy marks it as conditional.
- Writes and transformations are out of scope and cannot be enabled by
  weakening the read-only validator.
- Approval is tenant-scoped, time-bounded, attributable, and cannot expand the
  original task authority or budget.

### Classification and retention

- The initial classifications are `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, and
  `RESTRICTED`, matching the gateway's audit classification vocabulary.
- Every stored context, memory, result, and artifact records its owner,
  tenant/workspace, classification, provenance, retention, access policy,
  encryption, and deletion semantics.
- Task context is retained only for the task lifecycle by default.
- Generated reports and artifacts default to 30 days unless a tenant policy
  requires less or more.
- Governance audit records default to 7 years in immutable external storage;
  compliance-specific requirements may extend this period.
- Sensitive query results do not become long-term memory automatically.

### Audit and evidence

- The gateway's structured, correlation-linked, hash-chained events become the
  governance ledger.
- The production sink must be external and immutable/WORM; container logs
  alone are insufficient.
- Traces record identity, tenant, task, agent, model, context references,
  capability calls, policy decisions, approvals, query hashes, masking,
  artifacts, retries, failures, and cancellations.

### Autonomy boundary

- The first release supports L2 governed and L3 conditional read-only
  autonomy.
- L2 permits low-risk reads within policy and budgets.
- L3 permits policy-approved conditional reads and human-approved
  restricted/export flows.
- Scheduled or adaptive autonomy and all writes wait until read-only
  governance, evaluation, recovery, and audit are proven.

## First release slice

The first user-visible workflow is:

```text
user goal
→ tenant-filtered semantic discovery
→ typed read plan
→ policy-authorized governed execution
→ evidence-backed report
```

The existing Phase 4 integration proof demonstrates this path, including
tenant isolation, policy enforcement, read-only execution, provenance,
confidence, durable task tracing, and tenant-scoped report replay.

## Non-negotiable invariants

- No agent receives raw credentials.
- No request bypasses tenant resolution or policy evaluation.
- Only typed plans reach the SQL compiler.
- Analytical execution uses read-only database roles.
- Masking and resource budgets are enforced before results leave the kernel.
- Policy outages fail closed.
- Retries cannot increase authority or budgets.
- Every autonomous action is attributable and replayable.
