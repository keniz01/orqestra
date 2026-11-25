# orqestra

An AI-native autonomous data platform for discovering, understanding,
governing, and orchestrating enterprise data across multiple sources.

## Current status

The repository is being built in governed, reviewable slices. The current
foundations include:

- a transport-independent execution kernel;
- trusted principal and server-owned tenant binding contracts;
- deny-by-default capability policy evaluation;
- deterministic `sqlglot` validation for read-only SQL;
- policy-driven masking and result row/byte budgets;
- time-bounded agent delegation with task and agent audit identity;
- tenant-scoped task and plan state transitions;
- explicit tenant-scoped approval requests with separation of duties and expiry;
- append-only governance events with idempotent, tenant-scoped ledger reads.
- formal task, approval, and governance repository protocols with in-memory
  reference adapters.

The architecture and implementation boundaries are documented in
[`docs/ai-native-platform-index.md`](docs/ai-native-platform-index.md).
Persistence boundaries are documented in
[`docs/durable-control-plane-repositories.md`](docs/durable-control-plane-repositories.md).

## Development

Python 3.12+ is required. Install the runtime dependency and run the focused
test suites with:

```bash
python3 -m pip install "sqlglot>=26,<27" pytest
python3 -m pytest -q
```

The execution kernel is intentionally transport-independent. Database
connectors, HTTP APIs, model providers, and agent workers must use its typed
contracts rather than bypassing tenant resolution, policy, validation,
masking, budgets, or audit.

## Repository guardrails

- `.gitignore` excludes Python caches, virtual environments, build output, and
  local package artifacts.
- No agent receives raw database credentials.
- Policy failures remain fail-closed.
- Read execution remains bounded and read-only.
- Every task and capability invocation must remain tenant-scoped and
  attributable.
