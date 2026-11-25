# Governed read orchestrator

`governed_orchestrator.GovernedReadOrchestrator` coordinates a typed
`ReadWorkflowPlan` through the existing task, reliability, read-workflow,
execution-kernel, and connector-execution boundaries.

The orchestrator creates and transitions a tenant-scoped task, acquires an
exclusive lease, checkpoints progress, checks cancellation and lease ownership,
and invokes only an injected `GovernedCapabilityExecutor`. The executor
returns `GovernedCapabilityResult` values with provenance; the read workflow
runner assembles the final result and refuses to mark a workflow complete
without evidence and confidence.

The orchestrator does not accept SQL, model providers, credentials, connector
routing, or raw connector calls. Policy and connector authorization remain the
responsibility of the injected governed capability executor.
