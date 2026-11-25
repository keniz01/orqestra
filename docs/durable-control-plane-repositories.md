# Durable control-plane repository contracts

The control plane exposes repository protocols at each persistence boundary:

- `task_runtime.TaskRepository` stores tenant-owned tasks and requires
  optimistic `expected_version` checks for transitions.
- `approval_plane.ApprovalRepository` stores tenant-scoped approval requests,
  preserves separation of duties, and requires optimistic version checks for
  decisions.
- `governance.GovernanceRepository` (also named `GovernanceLedger` for
  compatibility) appends immutable events idempotently by `event_id` and
  returns only events for the caller's organization.

`InMemoryTaskRepository`, `InMemoryApprovalRepository`, and
`InMemoryGovernanceRepository` are contract-compatible reference adapters. The
existing `InMemoryTaskStore`, `ApprovalStore`, and `InMemoryGovernanceLedger`
names remain supported.

Durable adapters may use any storage technology, but must preserve the same
tenant boundary, version conflict behavior, append-only event identity, and
idempotent governance append semantics. Governance event sinks should not
include credentials or unrestricted data results in event payloads.
