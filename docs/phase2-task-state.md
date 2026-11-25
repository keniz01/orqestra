# Phase 2 — Task and Plan State Foundation

**Status:** Initial slice implemented

This slice introduces the first control-plane primitive for autonomous
execution: a tenant-scoped task aggregate with explicit plan steps and
optimistic-concurrency-protected state transitions.

## Implemented

- typed task and plan-step contracts;
- explicit pending, running, approval-waiting, completed, failed, and
  cancelled states;
- tenant and principal ownership checks on every read and transition;
- optimistic version checks to reject stale workers;
- invalid-transition rejection;
- in-memory reference store for local development and contract tests.

## Transition rules

```text
pending → running | cancelled
running → waiting_approval | completed | failed | cancelled
waiting_approval → running | cancelled
failed → running | cancelled
completed → terminal
cancelled → terminal
```

The in-memory store is not a production persistence layer. A durable adapter
must preserve the same ownership, version, transition, and audit invariants
before task execution is connected to workers or agents.

## Validation

```text
python3 -m pytest -q
13 passed
```
