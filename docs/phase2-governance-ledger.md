# Phase 2 — Governance Ledger Foundation

**Status:** Initial slice implemented

The governance foundation provides a typed, append-only event contract for
control-plane state changes. Task and approval stores can emit events through a
transport-independent sink, while the reference ledger provides idempotent
append and tenant-scoped reads.

## Implemented

- immutable tenant-scoped governance event contracts;
- idempotent event append by event ID;
- conflict detection when an event ID is reused with different data;
- tenant- and task-scoped event reads;
- task creation and transition events;
- approval creation, decision, and expiry events;
- in-memory reference ledger for local development and contract tests.

## Security boundary

Ledger reads remain organization-scoped. Production durable adapters must
preserve append-only semantics, event identity, tenant isolation, and
idempotency. Event payloads must contain governance metadata rather than raw
credentials or unrestricted data results.

## Validation

```text
python3 -m pytest -q
24 passed
```
