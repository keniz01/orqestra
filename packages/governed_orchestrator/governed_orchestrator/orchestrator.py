"""Model-independent orchestration for governed read workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from execution_kernel import Principal
from governance import GovernanceEvent, GovernanceLedger
from read_workflows import (
    CapabilityResultState,
    CritiqueState,
    Evidence,
    GovernedCapabilityResult,
    InMemoryReadWorkflowRunner,
    ReadPlanStep,
    ReadWorkflowPlan,
    ReadWorkflowReport,
    ReadWorkflowResult,
    ReadWorkflowCritic,
    WorkflowCritique,
    WorkflowResultState,
)
from task_runtime import PlanStep, Task, TaskRepository, TaskStatus
from workflow_reliability import (
    InMemoryCancellationStore,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    Checkpoint,
    Lease,
    WorkflowCancelled,
)
from .report_store import WorkflowReportStore


class GovernedCapabilityExecutor(Protocol):
    """The sole execution boundary used by the orchestrator."""

    def execute(
        self,
        principal: Principal,
        task_id: str,
        step: ReadPlanStep,
    ) -> GovernedCapabilityResult:
        """Invoke one already-governed capability without credentials."""


@dataclass(frozen=True, slots=True)
class GovernedReadOutcome:
    """The durable identifiers and result returned by an orchestration run."""

    task: Task
    result: ReadWorkflowResult
    checkpoint_version: int
    lease_id: str
    report: ReadWorkflowReport | None = None


class GovernedReadOrchestrator:
    """Create, govern, checkpoint, and complete one typed read workflow."""

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        leases: InMemoryLeaseStore,
        checkpoints: InMemoryCheckpointStore,
        cancellations: InMemoryCancellationStore,
        ledger: GovernanceLedger,
        executor: GovernedCapabilityExecutor,
        runner: InMemoryReadWorkflowRunner | None = None,
        critic: ReadWorkflowCritic | None = None,
        report_store: WorkflowReportStore | None = None,
        owner_id: str = "governed-read-orchestrator",
        lease_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tasks = tasks
        self._leases = leases
        self._checkpoints = checkpoints
        self._cancellations = cancellations
        self._ledger = ledger
        self._executor = executor
        self._runner = runner or InMemoryReadWorkflowRunner()
        self._critic = critic
        self._report_store = report_store
        self._owner_id = owner_id
        self._lease_ttl = lease_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        principal: Principal,
        plan: ReadWorkflowPlan,
    ) -> GovernedReadOutcome:
        task = self._tasks.create(
            principal,
            plan.goal,
            (
                PlanStep(step.step_id, step.capability, step.arguments)
                for step in plan.steps
            ),
        )
        task = self._tasks.transition(
            principal,
            task.task_id,
            TaskStatus.RUNNING,
            expected_version=task.version,
        )
        lease = self._leases.acquire(
            task.task_id,
            self._owner_id,
            self._lease_ttl,
            now=self._now(),
        )
        self._emit(
            principal,
            task.task_id,
            "workflow.started",
            "allow",
            "Governed read workflow started.",
            payload={"lease_id": lease.lease_id, "plan_steps": len(plan.steps)},
        )

        checkpoint = self._checkpoints.save(
            task.task_id,
            {"status": "running", "completed_steps": [], "completed_results": []},
            now=self._now(),
        )
        results: list[GovernedCapabilityResult] = []
        try:
            for step in plan.steps:
                self._ensure_lease(lease)
                self._cancellations.raise_if_cancelled(task.task_id)
                self._emit(
                    principal,
                    task.task_id,
                    "capability.invocation_started",
                    "allow",
                    "Invoking injected governed capability.",
                    capability=step.capability,
                    payload={"step_id": step.step_id},
                )
                try:
                    result = self._executor.execute(principal, task.task_id, step)
                except PermissionError as exc:
                    result = GovernedCapabilityResult(
                        step_id=step.step_id,
                        capability=step.capability,
                        state=CapabilityResultState.DENIED,
                        confidence=None,
                    )
                    self._emit(
                        principal,
                        task.task_id,
                        "capability.invocation_denied",
                        "deny",
                        str(exc) or "Governed capability denied.",
                        capability=step.capability,
                        payload={"step_id": step.step_id},
                    )
                except Exception as exc:
                    result = GovernedCapabilityResult(
                        step_id=step.step_id,
                        capability=step.capability,
                        state=CapabilityResultState.FAILED,
                    )
                    self._emit(
                        principal,
                        task.task_id,
                        "capability.invocation_failed",
                        "deny",
                        str(exc) or "Governed capability failed.",
                        capability=step.capability,
                        payload={"step_id": step.step_id},
                    )
                if result.step_id != step.step_id or result.capability != step.capability:
                    raise ValueError("Executor result does not match the planned step.")
                results.append(result)
                checkpoint = self._checkpoints.save(
                    task.task_id,
                    {
                        "status": "running",
                        "completed_steps": [item.step_id for item in results],
                        "completed_results": [
                            self._serialize_result(item) for item in results
                        ],
                    },
                    expected_version=checkpoint.version,
                    now=self._now(),
                )
                self._emit(
                    principal,
                    task.task_id,
                    "workflow.checkpointed",
                    "allow",
                    "Workflow progress checkpointed.",
                    capability=step.capability,
                    payload={"step_id": step.step_id, "version": checkpoint.version},
                )
                self._ensure_lease(lease)
            self._cancellations.raise_if_cancelled(task.task_id)
            result = self._review(plan, self._runner.run(plan, results))
        except WorkflowCancelled as exc:
            result = ReadWorkflowResult(
                state=WorkflowResultState.CANCELLED,
                reason=str(exc),
            )
            task, checkpoint = self._finish(
                principal, task, TaskStatus.CANCELLED, result, checkpoint
            )
            self._release(lease)
            return self._outcome(task, result, checkpoint, lease.lease_id, plan)

        except (LookupError, PermissionError) as exc:
            result = ReadWorkflowResult(
                state=WorkflowResultState.FAILED,
                reason=str(exc),
            )
            task, checkpoint = self._finish(
                principal, task, TaskStatus.FAILED, result, checkpoint
            )
            self._release(lease)
            return self._outcome(task, result, checkpoint, lease.lease_id, plan)

        task_status = (
            TaskStatus.COMPLETED
            if result.state is WorkflowResultState.COMPLETED
            else TaskStatus.FAILED
        )
        task, checkpoint = self._finish(
            principal, task, task_status, result, checkpoint
        )
        self._release(lease)
        return self._outcome(task, result, checkpoint, lease.lease_id, plan)

    def resume(
        self,
        principal: Principal,
        plan: ReadWorkflowPlan,
        task_id: str,
    ) -> GovernedReadOutcome:
        """Resume a running task from its latest checkpoint."""

        task = self._tasks.get(principal, task_id)
        checkpoint = self._checkpoints.latest(task_id)
        if checkpoint is None:
            raise LookupError("Workflow checkpoint was not found.")
        results = [
            self._deserialize_result(item)
            for item in checkpoint.state.get("completed_results", [])
        ]
        completed_steps = {
            item.step_id for item in results
        } | set(checkpoint.state.get("completed_steps", []))
        lease = self._leases.acquire(
            task_id,
            self._owner_id,
            self._lease_ttl,
            now=self._now(),
        )
        try:
            for step in plan.steps:
                if step.step_id in completed_steps:
                    continue
                self._ensure_lease(lease)
                self._cancellations.raise_if_cancelled(task_id)
                try:
                    result = self._executor.execute(principal, task_id, step)
                except PermissionError:
                    result = GovernedCapabilityResult(
                        step_id=step.step_id,
                        capability=step.capability,
                        state=CapabilityResultState.DENIED,
                    )
                except Exception:
                    result = GovernedCapabilityResult(
                        step_id=step.step_id,
                        capability=step.capability,
                        state=CapabilityResultState.FAILED,
                    )
                if result.step_id != step.step_id or result.capability != step.capability:
                    raise ValueError("Executor result does not match the planned step.")
                results.append(result)
                checkpoint = self._checkpoints.save(
                    task_id,
                    {
                        "status": "running",
                        "completed_steps": [item.step_id for item in results],
                        "completed_results": [
                            self._serialize_result(item) for item in results
                        ],
                    },
                    expected_version=checkpoint.version,
                    now=self._now(),
                )
            result = self._review(plan, self._runner.run(plan, results))
        except WorkflowCancelled as exc:
            result = ReadWorkflowResult(
                state=WorkflowResultState.CANCELLED,
                reason=str(exc),
            )
            task, checkpoint = self._finish(
                principal, task, TaskStatus.CANCELLED, result, checkpoint
            )
            self._release(lease)
            return self._outcome(task, result, checkpoint, lease.lease_id, plan)
        except (LookupError, PermissionError) as exc:
            result = ReadWorkflowResult(
                state=WorkflowResultState.FAILED,
                reason=str(exc),
            )
            task, checkpoint = self._finish(
                principal, task, TaskStatus.FAILED, result, checkpoint
            )
            self._release(lease)
            return self._outcome(task, result, checkpoint, lease.lease_id, plan)

        task_status = (
            TaskStatus.COMPLETED
            if result.state is WorkflowResultState.COMPLETED
            else TaskStatus.FAILED
        )
        task, checkpoint = self._finish(
            principal, task, task_status, result, checkpoint
        )
        self._release(lease)
        return self._outcome(task, result, checkpoint, lease.lease_id, plan)

    @staticmethod
    def _serialize_result(result: GovernedCapabilityResult) -> dict[str, object]:
        return {
            "step_id": result.step_id,
            "capability": result.capability,
            "state": result.state.value,
            "value": result.value,
            "confidence": result.confidence,
            "query_hash": result.query_hash,
            "evidence": [
                {
                    "source": item.source,
                    "reference": item.reference,
                    "capability": item.capability,
                    "observed_at": item.observed_at.isoformat(),
                    "metadata": dict(item.metadata),
                    "query_hash": item.query_hash,
                }
                for item in result.evidence
            ],
        }

    @staticmethod
    def _deserialize_result(raw: dict[str, object]) -> GovernedCapabilityResult:
        return GovernedCapabilityResult(
            step_id=str(raw["step_id"]),
            capability=str(raw["capability"]),
            state=CapabilityResultState(str(raw["state"])),
            value=raw.get("value"),
            confidence=raw.get("confidence"),
            query_hash=raw.get("query_hash"),
            evidence=tuple(
                Evidence(
                    source=str(item["source"]),
                    reference=str(item["reference"]),
                    capability=str(item["capability"]),
                    observed_at=datetime.fromisoformat(str(item["observed_at"])),
                    metadata=item.get("metadata", {}),
                    query_hash=item.get("query_hash"),
                )
                for item in raw.get("evidence", [])
            ),
        )

    def _review(
        self, plan: ReadWorkflowPlan, result: ReadWorkflowResult
    ) -> ReadWorkflowResult:
        if result.state is not WorkflowResultState.COMPLETED:
            return result
        critique = (
            self._critic.critique(plan, result)
            if self._critic is not None
            else WorkflowCritique(
                state=CritiqueState.ACCEPTED,
                reason="Evidence and confidence requirements were satisfied.",
                confidence=result.confidence,
            )
        )
        if critique.state is CritiqueState.ACCEPTED:
            return replace(result, critique=critique)
        state = (
            WorkflowResultState.BLOCKED
            if critique.state is CritiqueState.REJECTED
            else WorkflowResultState.PARTIAL
        )
        return replace(
            result,
            state=state,
            critique=critique,
            reason=critique.reason,
        )

    def _outcome(
        self,
        task: Task,
        result: ReadWorkflowResult,
        checkpoint: Checkpoint,
        lease_id: str,
        plan: ReadWorkflowPlan,
    ) -> GovernedReadOutcome:
        result = replace(result, trace_id=task.task_id)
        report = ReadWorkflowReport.from_result(
            plan.goal, result, trace_id=task.task_id
        )
        if self._report_store is not None:
            self._report_store.save(task.owner.org_id, report)
        return GovernedReadOutcome(
            task,
            result,
            checkpoint.version,
            lease_id,
            report,
        )

    def report_for(
        self, principal: Principal, trace_id: str
    ) -> ReadWorkflowReport | None:
        """Replay a report only within the trusted principal's tenant."""

        if self._report_store is None:
            return None
        return self._report_store.get(principal.org_id, trace_id)

    def _finish(
        self,
        principal: Principal,
        task: Task,
        status: TaskStatus,
        result: ReadWorkflowResult,
        checkpoint: Checkpoint,
    ) -> tuple[Task, Checkpoint]:
        checkpoint_version = checkpoint.version
        checkpoint = self._checkpoints.save(
            task.task_id,
            {"status": result.state.value, "reason": result.reason},
            expected_version=checkpoint_version,
            now=self._now(),
        )
        updated = self._tasks.transition(
            principal,
            task.task_id,
            status,
            expected_version=task.version,
        )
        self._emit(
            principal,
            task.task_id,
            "workflow.finished",
            "allow" if result.state is WorkflowResultState.COMPLETED else "deny",
            result.reason or "Governed read workflow completed.",
            payload={"state": result.state.value},
        )
        return updated, checkpoint

    def _release(self, lease: Lease) -> None:
        try:
            self._leases.release(
                lease.workflow_id,
                lease.lease_id,
                lease.owner_id,
                now=self._now(),
            )
        except (LookupError, PermissionError):
            pass

    def _ensure_lease(self, lease: Lease) -> None:
        current = self._leases.get(lease.workflow_id, now=self._now())
        if current is None or current.lease_id != lease.lease_id:
            raise PermissionError("Workflow lease is stale or expired.")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now

    def _emit(
        self,
        principal: Principal,
        task_id: str,
        event_type: str,
        decision: str,
        reason: str,
        *,
        capability: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._ledger.append(
            GovernanceEvent(
                org_id=principal.org_id,
                event_type=event_type,
                actor_user_id=principal.user_id,
                decision=decision,
                reason=reason,
                task_id=task_id,
                capability=capability,
                payload=payload or {},
            )
        )
