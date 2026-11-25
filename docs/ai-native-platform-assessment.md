# Existing Architecture Assessment

**Status:** Living assessment
**Last reviewed:** 2026-11-25
**Baseline:** `c1345bab06b7c89062b6484e262dc5df1557dd79`

## Executive assessment

The repository is a security-focused, read-only data gateway. It has a strong
deterministic execution and governance core, but its product model is still
request/response-centric. AI is currently an enhancement for text-to-SQL,
schema retrieval, result presentation, and greetings rather than the primary
execution model.

The correct greenfield strategy is to preserve and extract the security and
execution kernel, then build durable tasks, typed capabilities, semantic
context, agent delegation, memory, approvals, and autonomous orchestration
around it.

## Current system

| Area | Current implementation | Assessment |
|---|---|---|
| Experience | React 19/Vite/TypeScript workspace, schema browser, SQL editor, results | Useful foundation, but SQL is the primary interaction model |
| Authentication | Auth0/OIDC, PKCE, validated JWTs, HttpOnly sessions, Redis | Preserve as the human identity boundary |
| BFF | FastAPI auth service forwards authenticated GraphQL calls | Evolve into the public control/API boundary |
| Query API | FastAPI, Strawberry GraphQL, SQLAlchemy, async database access | Extract deterministic capabilities from the transport layer |
| Authorization | OPA plus a deprecated in-process evaluator | Expand from SQL decisions to all capabilities |
| Tenant routing | Opaque logical database IDs resolved server-side | Preserve as a hard isolation boundary |
| SQL safety | `sqlparse`, `sqlglot`, forbidden constructs, AST analysis | Preserve and place inside a typed query compiler |
| Execution | Read-only role, read-only transaction, limits, timeout, masking | Preserve as the execution kernel |
| AI | Embeddings, text-to-SQL, bounded correction retries, presentation planning | Reframe as agents producing typed plans and evidence |
| Audit | Structured events, correlation IDs, hash chaining, configurable sinks | Expand into a task, reasoning, capability, and provenance ledger |
| Operations | Rate limits, tenant quotas, incident response, encryption, telemetry | Reuse as platform controls and autonomous safety mechanisms |
| Delivery | Hardened Compose, CI security gates, policy validation, signed images | Preserve supply-chain and runtime posture |

## Capabilities to preserve

### Identity and trust

- Validated Auth0 JWTs with issuer, audience, expiry, signature, and scope
  checks.
- Immutable `Principal` objects derived only from trusted claims.
- Required tenant claim and rejection of incomplete identity.
- Removal of spoofable `X-User-*`, `X-Org-*`, and `X-Tenant-*` headers.
- HttpOnly, Secure, SameSite session cookies.
- Redis-backed sessions with TTL and production fail-fast behavior.
- PKCE and layered CSRF checks.

### Authorization and isolation

- OPA policy evaluation with deny precedence.
- Fail-closed behavior when OPA is unavailable.
- RBAC hierarchy and separation-of-duty support.
- Server-owned `(org_id, database_id)` resolution.
- Policy-filtered schema visibility.
- AST-level row restrictions.
- Column allowlists and source-level masking.
- Explainable policy decisions.

### Deterministic data safety

- One governed query pipeline for all access modes.
- SELECT/WITH-only validation.
- `sqlparse` and `sqlglot` analysis.
- Rejection of mutations, dangerous functions, comments, multi-statements,
  system tables, malformed input, and oversized queries.
- Parameterized execution.
- Database-enforced read-only roles and transactions.
- Cost, timeout, row, byte, pool, and connection limits.
- Per-tenant queue and concurrency quotas.
- Layered rate limits.

### Governance and operations

- Correlation IDs and distributed telemetry.
- Tamper-evident audit hash chaining.
- Generic client errors with detailed server-side diagnostics.
- IP blocking, session revocation, and tenant isolation.
- Envelope encryption with pluggable KMS/Vault backends.
- Network segmentation and hardened containers.
- Security, fuzzing, authorization, tenant-isolation, and resource-control
  tests.

## Current limitations

- AI output is still SQL text instead of a typed, inspectable plan.
- There is no durable task/workflow state machine.
- There is no distinct agent identity or delegated capability token.
- There is no registry describing tools, risk, budgets, or approvals.
- There is no human approval or just-in-time access workflow.
- Schema retrieval is not yet a full policy-aware semantic catalog.
- Audit records focus on requests and executions, not complete task provenance.
- Autonomous retries, checkpointing, cancellation, recovery, and replay are
  not first-class.
- The production roadmap still identifies agent identity/MCP, JIT approval,
  enterprise identity, AI evaluations, audit UI/export, dashboards, capacity
  validation, and formal security sign-off as open product or operational work.

## Architectural conclusion

The existing repository should not be extended into an agent wrapper. The
greenfield platform should extract the following stable kernel:

```text
trusted principal
→ tenant/database binding
→ capability policy decision
→ typed query compilation
→ row/column enforcement
→ read-only execution
→ resource controls
→ masking
→ audit and provenance
```

Everything above that kernel should be redesigned around goals, tasks, plans,
agents, context, memory, approvals, and autonomous execution.
