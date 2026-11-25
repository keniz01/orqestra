# Phase 2 — Approval Plane Foundation

**Status:** Initial slice implemented

This slice introduces explicit, tenant-scoped approval requests for
capabilities that require human authorization.

## Implemented

- typed pending, approved, rejected, and expired approval states;
- task and capability binding;
- request expiry;
- same-tenant approval enforcement;
- separation of duties: requesters cannot approve themselves;
- optimistic version checks;
- approval validation that matches task and capability;
- execution-kernel enforcement for approval-required capabilities;
- in-memory reference store for local development and contract tests.

## Security boundary

Approval is an authority grant, not a user-interface event. A production
adapter must persist the same tenant, requester, approver, expiry, version, and
capability invariants, and every approved capability invocation must validate
the approval against its task and capability before execution.

## Validation

```text
python3 -m pytest -q
15 passed
```
