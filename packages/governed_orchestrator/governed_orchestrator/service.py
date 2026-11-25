"""Goal-to-plan service with bounded, fail-closed replanning."""

from __future__ import annotations

from execution_kernel import Principal
from read_workflows import (
    ContextAwareReadWorkflowPlanner,
    GovernedContext,
    ReadWorkflowPlan,
    ReadWorkflowReplanner,
    WorkflowResultState,
)

from .orchestrator import GovernedReadOutcome, GovernedReadOrchestrator


class WorkflowReplanLimitError(PermissionError):
    """Raised when a replacement plan broadens authority or budgets."""


class GovernedReadWorkflowService:
    """Connect trusted context, planning, orchestration, and bounded replans."""

    def __init__(
        self,
        orchestrator: GovernedReadOrchestrator,
        planner: ContextAwareReadWorkflowPlanner,
        *,
        replanner: ReadWorkflowReplanner | None = None,
        max_replans: int = 1,
    ) -> None:
        if max_replans < 0:
            raise ValueError("max_replans must not be negative")
        self._orchestrator = orchestrator
        self._planner = planner
        self._replanner = replanner
        self._max_replans = max_replans

    def run_goal(
        self,
        principal: Principal,
        goal: str,
        context: GovernedContext,
    ) -> GovernedReadOutcome:
        plan = self._planner.plan_for(principal, goal, context)
        return self.run_plan(principal, plan)

    def run_plan(
        self, principal: Principal, plan: ReadWorkflowPlan
    ) -> GovernedReadOutcome:
        original_capabilities = {step.capability for step in plan.steps}
        original_budget = plan.budget
        for attempt in range(self._max_replans + 1):
            outcome = self._orchestrator.run(principal, plan)
            critique = outcome.result.critique
            if (
                critique is None
                or outcome.result.state is not WorkflowResultState.PARTIAL
                or self._replanner is None
                or attempt >= self._max_replans
            ):
                return outcome
            replacement = self._replanner.replan(
                plan.goal, plan, outcome.result, attempt + 1
            )
            if replacement.budget.max_steps > original_budget.max_steps:
                raise WorkflowReplanLimitError(
                    "Replanning cannot increase the workflow step budget."
                )
            if replacement.budget.max_evidence > original_budget.max_evidence:
                raise WorkflowReplanLimitError(
                    "Replanning cannot increase the workflow evidence budget."
                )
            if not {
                step.capability for step in replacement.steps
            }.issubset(original_capabilities):
                raise WorkflowReplanLimitError(
                    "Replanning cannot broaden workflow capabilities."
                )
            plan = replacement
        raise AssertionError("bounded replanning loop exhausted unexpectedly")
