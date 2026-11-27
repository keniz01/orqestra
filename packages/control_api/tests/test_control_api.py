from __future__ import annotations

from dataclasses import dataclass

import pytest
from execution_kernel import Principal
from read_workflows import GovernedContext, ReadWorkflowReport, WorkflowResultState

from control_api import GovernedReadControl, GoalRequest


@dataclass
class ContextProvider:
    context: GovernedContext
    calls: list[tuple[str, str]]

    def build(self, principal: Principal, goal: str) -> GovernedContext:
        self.calls.append((principal.org_id, goal))
        return self.context


@dataclass
class FakeService:
    report: ReadWorkflowReport

    def run_goal(self, principal, goal, context):
        assert context.tenant_id == principal.org_id
        assert goal == self.report.goal
        return type(
            "Outcome",
            (),
            {"task": type("Task", (), {"task_id": self.report.trace_id})(), "report": self.report},
        )()

    def report_for(self, principal, trace_id):
        return self.report if trace_id == self.report.trace_id else None


def test_goal_boundary_assembles_context_and_replays_tenant_scoped_report():
    principal = Principal("user-1", "org-1", frozenset({"viewer"}))
    report = ReadWorkflowReport(
        goal="compare monthly revenue",
        state=WorkflowResultState.COMPLETED,
        values={"amount": 42},
        citations=("warehouse:revenue",),
        query_hashes=("abc123",),
        confidence=0.9,
        trace_id="task-1",
    )
    service = FakeService(report)
    provider = ContextProvider(GovernedContext("org-1", ()), [])
    control = GovernedReadControl(service, provider)

    response = control.submit(principal, GoalRequest(report.goal))

    assert response.trace_id == "task-1"
    assert response.report == report
    assert provider.calls == [("org-1", report.goal)]
    assert control.report_for(principal, "task-1") == report
    with pytest.raises(ValueError):
        control.submit(principal, GoalRequest("   "))
