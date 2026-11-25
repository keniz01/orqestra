from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from execution_kernel import Principal
from governed_orchestrator import GovernedReadOrchestrator
from governance import InMemoryGovernanceLedger
from read_workflows import (
    CapabilityResultState,
    Evidence,
    GovernedCapabilityResult,
    ReadPlanStep,
    ReadWorkflowPlan,
    WorkflowResultState,
)
from task_runtime import InMemoryTaskStore, TaskStatus
from workflow_reliability import (
    InMemoryCancellationStore,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PRINCIPAL = Principal(user_id="user-1", org_id="org-1")
PLAN = ReadWorkflowPlan(
    goal="Find revenue",
    steps=(ReadPlanStep("revenue", "catalog.metric", {"metric": "revenue"}),),
)


def build(executor, *, clock=lambda: NOW, ttl=timedelta(minutes=5)):
    ledger = InMemoryGovernanceLedger()
    tasks = InMemoryTaskStore()
    orchestrator = GovernedReadOrchestrator(
        tasks=tasks,
        leases=InMemoryLeaseStore(),
        checkpoints=InMemoryCheckpointStore(),
        cancellations=InMemoryCancellationStore(),
        ledger=ledger,
        executor=executor,
        owner_id="worker-1",
        lease_ttl=ttl,
        clock=clock,
    )
    return orchestrator, ledger, tasks


def success(step):
    return GovernedCapabilityResult(
        step_id=step.step_id,
        capability=step.capability,
        state=CapabilityResultState.SUCCEEDED,
        value={"amount": 42},
        evidence=(Evidence("catalog", "metric:revenue", step.capability),),
        confidence=0.9,
    )


def test_happy_path_creates_task_checkpoints_and_emits_events():
    orchestrator, ledger, _ = build(
        type("Executor", (), {"execute": lambda self, principal, task_id, step: success(step)})()
    )

    outcome = orchestrator.run(PRINCIPAL, PLAN)

    assert outcome.task.status is TaskStatus.COMPLETED
    assert outcome.result.state is WorkflowResultState.COMPLETED
    assert outcome.checkpoint_version == 3
    assert {event.event_type for event in ledger.events_for(PRINCIPAL, task_id=outcome.task.task_id)} >= {
        "workflow.started",
        "workflow.checkpointed",
        "workflow.finished",
    }


@pytest.mark.parametrize("denial", [PermissionError("policy denied"), CapabilityResultState.DENIED])
def test_policy_or_executor_denial_is_blocked(denial):
    def execute(self, principal, task_id, step):
        if isinstance(denial, Exception):
            raise denial
        return GovernedCapabilityResult(step.step_id, step.capability, denial)

    orchestrator, _, _ = build(type("Executor", (), {"execute": execute})())
    outcome = orchestrator.run(PRINCIPAL, PLAN)

    assert outcome.result.state is WorkflowResultState.BLOCKED
    assert outcome.task.status is TaskStatus.FAILED


def test_cancellation_stops_before_capability_invocation():
    calls = 0

    def execute(principal, task_id, step):
        nonlocal calls
        calls += 1
        return success(step)

    cancellation_store = InMemoryCancellationStore()
    ledger = InMemoryGovernanceLedger()
    tasks = InMemoryTaskStore()
    orchestrator = GovernedReadOrchestrator(
        tasks=tasks,
        leases=InMemoryLeaseStore(),
        checkpoints=InMemoryCheckpointStore(),
        cancellations=cancellation_store,
        ledger=ledger,
        executor=type("Executor", (), {"execute": execute})(),
        clock=lambda: NOW,
    )
    original_create = tasks.create

    def create(*args, **kwargs):
        task = original_create(*args, **kwargs)
        cancellation_store.request(task.task_id)
        return task

    tasks.create = create
    outcome = orchestrator.run(PRINCIPAL, PLAN)

    assert outcome.result.state is WorkflowResultState.CANCELLED
    assert outcome.task.status is TaskStatus.CANCELLED
    assert calls == 0


def test_stale_lease_fails_without_completing():
    times = iter((NOW, NOW, NOW + timedelta(seconds=2)))
    orchestrator, _, _ = build(
        type("Executor", (), {"execute": lambda self, principal, task_id, step: success(step)})(),
        clock=lambda: next(times, NOW + timedelta(seconds=2)),
        ttl=timedelta(seconds=1),
    )

    outcome = orchestrator.run(PRINCIPAL, PLAN)

    assert outcome.result.state is WorkflowResultState.FAILED
    assert "lease" in (outcome.result.reason or "").lower()
    assert outcome.task.status is TaskStatus.FAILED


def test_missing_evidence_is_partial_and_not_completed():
    orchestrator, _, _ = build(
        type(
            "Executor",
            (),
            {
                "execute": lambda self, principal, task_id, step: GovernedCapabilityResult(
                    step.step_id,
                    step.capability,
                    CapabilityResultState.SUCCEEDED,
                    value={"amount": 42},
                    confidence=0.9,
                )
            },
        )()
    )

    outcome = orchestrator.run(PRINCIPAL, PLAN)

    assert outcome.result.state is WorkflowResultState.PARTIAL
    assert outcome.task.status is TaskStatus.FAILED
