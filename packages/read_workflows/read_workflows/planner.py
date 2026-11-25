"""Deterministic, credential-free planning for governed read workflows."""

from __future__ import annotations

from dataclasses import dataclass

from execution_kernel import Principal

from .context import GovernedContext
from .contracts import ReadPlanStep, ReadWorkflowPlan, WorkflowBudget


@dataclass(frozen=True, slots=True)
class PlannedGoal:
    """A trusted principal's goal paired with bounded governed context."""

    principal: Principal
    goal: str
    context: GovernedContext


class DeterministicReadWorkflowPlanner:
    """Turn a goal into typed intent without producing SQL or credentials."""

    def plan(self, goal: str) -> ReadWorkflowPlan:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        return ReadWorkflowPlan(
            goal=goal,
            steps=(
                ReadPlanStep(
                    "discover",
                    "catalog.search_semantic_metadata",
                    {"goal": goal.strip()},
                ),
            ),
        )

    def plan_for(
        self,
        principal: Principal,
        goal: str,
        context: GovernedContext,
        *,
        budget: WorkflowBudget | None = None,
    ) -> ReadWorkflowPlan:
        if context.tenant_id != principal.org_id:
            raise PermissionError("planning context crossed the tenant boundary")
        planned = self.plan(goal)
        steps = list(planned.steps)
        if context.catalog:
            steps.append(
                ReadPlanStep(
                    "read",
                    "data.plan_read_query",
                    {
                        "goal": planned.goal,
                        "source_ids": tuple(
                            source.source_id for source in context.catalog
                        ),
                    },
                )
            )
        return ReadWorkflowPlan(
            goal=planned.goal,
            steps=tuple(steps),
            budget=budget or planned.budget,
        )
