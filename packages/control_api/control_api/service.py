"""Goal submission and tenant-scoped report retrieval contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from execution_kernel import Principal
from governed_orchestrator import GovernedReadOutcome, GovernedReadWorkflowService
from read_workflows import GovernedContext, ReadWorkflowReport


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class GoalRequest:
    """A user goal; context is assembled by a trusted server-side provider."""

    goal: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _required_text(self.goal, "goal"))


@dataclass(frozen=True, slots=True)
class GoalResponse:
    """The durable trace and report returned by a governed goal execution."""

    trace_id: str
    report: ReadWorkflowReport

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _required_text(self.trace_id, "trace_id"))
        if self.report.trace_id != self.trace_id:
            raise ValueError("report trace_id must match response trace_id")


class ReadContextProvider(Protocol):
    """Build policy-filtered context without accepting client-supplied secrets."""

    def build(self, principal: Principal, goal: str) -> GovernedContext:
        """Return tenant-scoped context for a validated goal."""


class GovernedReadControl:
    """Expose the first product boundary without exposing orchestration internals."""

    def __init__(
        self,
        service: GovernedReadWorkflowService,
        context_provider: ReadContextProvider,
    ) -> None:
        self._service = service
        self._context_provider = context_provider

    def submit(self, principal: Principal, request: GoalRequest) -> GoalResponse:
        context = self._context_provider.build(principal, request.goal)
        outcome = self._service.run_goal(principal, request.goal, context)
        return self._response(outcome)

    def report_for(
        self, principal: Principal, trace_id: str
    ) -> ReadWorkflowReport | None:
        trace_id = _required_text(trace_id, "trace_id")
        return self._service.report_for(principal, trace_id)

    @staticmethod
    def _response(outcome: GovernedReadOutcome) -> GoalResponse:
        if outcome.report is None:
            raise RuntimeError("Completed goal execution did not produce a report.")
        return GoalResponse(trace_id=outcome.task.task_id, report=outcome.report)
