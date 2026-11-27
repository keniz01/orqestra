"""Typed planning for governed read workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from execution_kernel import Principal

from .context import GovernedContext
from .contracts import (
    PlanProvenance,
    ReadPlanStep,
    ReadWorkflowPlan,
    WorkflowBudget,
)


@dataclass(frozen=True, slots=True)
class PlannedGoal:
    """A trusted principal's goal paired with bounded governed context."""

    principal: Principal
    goal: str
    context: GovernedContext


class TypedPlanGenerator(Protocol):
    """A model boundary that can return typed plans but never raw SQL."""

    def generate(
        self, principal: Principal, goal: str, context: GovernedContext
    ) -> ReadWorkflowPlan:
        ...


class AllowlistedPlanProvider:
    """Select one configured plan generator and reject unapproved capabilities."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        generators: dict[str, TypedPlanGenerator],
        allowed_capabilities: frozenset[str],
    ) -> None:
        if not provider.strip() or not model.strip() or not prompt_version.strip():
            raise ValueError("provider, model, and prompt_version are required")
        if not allowed_capabilities:
            raise ValueError("allowed_capabilities must not be empty")
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version
        self._generators = dict(generators)
        self._allowed_capabilities = frozenset(allowed_capabilities)

    def plan(
        self, principal: Principal, goal: str, context: GovernedContext
    ) -> ReadWorkflowPlan:
        generator = self._generators.get(self._model)
        if generator is None:
            raise PermissionError("Configured model is not allowlisted.")
        plan = generator.generate(principal, goal, context)
        if not isinstance(plan, ReadWorkflowPlan):
            raise TypeError("Model provider must return a typed workflow plan.")
        if any(
            step.capability not in self._allowed_capabilities for step in plan.steps
        ):
            raise PermissionError("Model plan requested a capability outside the allowlist.")
        references = _context_references(context)
        return ReadWorkflowPlan(
            goal=plan.goal,
            steps=plan.steps,
            budget=plan.budget,
            provenance=PlanProvenance(
                provider=self._provider,
                model=self._model,
                prompt_version=self._prompt_version,
                context_references=references,
            ),
        )


class ReferenceTypedPlanGenerator:
    """Credential-free typed generator used when no external model is configured."""

    def generate(
        self, principal: Principal, goal: str, context: GovernedContext
    ) -> ReadWorkflowPlan:
        return DeterministicReadWorkflowPlanner().plan_for(
            principal,
            goal,
            context,
        )


class ModelReadWorkflowPlanner:
    """Validate model output before it reaches the governed orchestrator."""

    def __init__(self, provider: AllowlistedPlanProvider) -> None:
        self._provider = provider

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
        plan = self._provider.plan(principal, goal, context)
        if plan.goal != goal.strip():
            raise ValueError("Model plan goal does not match the requested goal.")
        if budget is not None and len(plan.steps) > budget.max_steps:
            raise ValueError("Model plan exceeds the requested workflow budget.")
        return plan if budget is None else ReadWorkflowPlan(
            goal=plan.goal,
            steps=plan.steps,
            budget=budget,
            provenance=plan.provenance,
        )


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


def _context_references(context: GovernedContext) -> tuple[str, ...]:
    catalog = tuple(f"catalog:{source.source_id}" for source in context.catalog)
    memories = tuple(
        f"memory:{memory.provenance.source_id}"
        for memory in context.memories
    )
    return tuple(dict.fromkeys((*catalog, *memories)))
