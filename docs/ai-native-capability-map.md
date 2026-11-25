# Existing-to-Target Capability Map

**Status:** Living mapping
**Last reviewed:** 2026-11-25

| Existing capability | Target role | Migration direction |
|---|---|---|
| Auth0 JWT validation | Identity plane | Extract into a reusable trusted-principal service |
| HttpOnly sessions and CSRF | Browser/session boundary | Preserve; connect sessions to tasks and approvals |
| Immutable `Principal` | Human, service, and agent identity contract | Extend with delegation and task context |
| OPA policy evaluation | Capability-wide policy/risk plane | Generalize beyond SQL operations |
| RBAC1 and SoD | Role and delegation policy | Preserve; add agent and approval constraints |
| Tenant database resolver | Connector broker and tenant binding | Preserve server-owned routing and secret isolation |
| `GovernedQueryGateway` | Deterministic execution kernel | Extract from GraphQL and make transport-independent |
| `SqlSafetyChecker` and `sqlglot` | Typed query compiler | Validate query IR and generated SQL independently |
| Row restrictions | Policy-generated execution constraints | Preserve AST-level enforcement |
| Column masking | Data protection transformation | Preserve source-level rewrite and post-result defense |
| Read-only roles/transactions | Connector safety invariant | Preserve for every analytical connector |
| Cost/timeout/row/byte limits | Capability budgets and scheduler quotas | Apply to plans, steps, and connectors |
| Rate limiting | Admission control | Extend to task, agent, tenant, and capability dimensions |
| Schema introspection | Semantic catalog ingestion | Store governed metadata, lineage, and quality |
| Embedding retrieval | Policy-filtered context retrieval | Add provenance and classification filtering |
| Text-to-SQL | Query-planning agent | Replace direct SQL generation with typed query intent |
| LLM result presentation | Report/artifact capability | Add evidence, citations, confidence, and replay links |
| Correlation IDs | Task/trace/span identity | Connect every action to a durable task |
| Audit hash chaining | Governance ledger | Record reasoning inputs, plans, approvals, and artifacts |
| Incident response manager | Autonomous safety controls | Add task cancellation and capability revocation |
| Envelope encryption | Memory/artifact/credential protection | Preserve and extend by data class |
| Redis session store | Distributed state and leases | Add task state, locks, idempotency, and checkpoints |
| Nginx edge | Experience/API boundary | Preserve TLS, headers, rate limiting, and routing |
| Docker network segmentation | Runtime isolation | Extend with connector and worker isolation |
| CI security gates | Agent/tool supply-chain controls | Add trajectory, prompt-injection, and policy regressions |
| Security/fuzz tests | AI safety evaluation suite | Preserve tests and add adversarial agent scenarios |
| Operator CLI | Headless capability client | Require delegated, governed access |

## Critical redesigns

### Text-to-SQL

`TextToSqlService` must not remain a path from natural language directly to
execution. The future flow is:

```text
user goal
→ semantic retrieval
→ typed QueryIntent
→ policy and risk evaluation
→ relational query plan
→ deterministic SQL compilation
→ governed execution kernel
→ evidence-backed result
```

### Policy

Policy decisions must cover capabilities, not just tables:

```text
principal + delegation + task + purpose + capability + data scope
→ policy decision + constraints
```

### Audit

The audit record must explain not only what SQL ran, but why the task ran,
which agent proposed it, which context was used, which policy allowed it, what
approval was granted, and which artifact was produced.
