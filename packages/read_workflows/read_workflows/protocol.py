"""Planner and runner boundaries for governed read workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .contracts import (
    GovernedCapabilityResult,
    ReadWorkflowPlan,
    ReadWorkflowResult,
    WorkflowCritique,
)


class ReadWorkflowPlanner(Protocol):
    """Produces typed intent only; it has no capability or credential access."""

    def plan(self, goal: str) -> ReadWorkflowPlan:
        """Return a model-independent plan for a user goal."""


class ContextAwareReadWorkflowPlanner(Protocol):
    """Plans only from trusted identity and already-filtered context."""

    def plan_for(
        self, principal: Any, goal: str, context: Any
    ) -> ReadWorkflowPlan:
        """Return typed intent without SQL, credentials, or connector routing."""


class ReadWorkflowReplanner(Protocol):
    """Produces a bounded replacement plan after a critique."""

    def replan(
        self,
        goal: str,
        previous: ReadWorkflowPlan,
        result: ReadWorkflowResult,
        attempt: int,
    ) -> ReadWorkflowPlan:
        """Return a plan that does not broaden the original authority."""


class ReadWorkflowRunner(Protocol):
    """Consumes plans and injected governed results without executing them."""

    def run(
        self,
        plan: ReadWorkflowPlan,
        results: Sequence[GovernedCapabilityResult],
    ) -> ReadWorkflowResult:
        """Assemble a workflow result from already-governed capability results."""


class ReadWorkflowCritic(Protocol):
    """Reviews a result without receiving credentials or executable SQL."""

    def critique(
        self, plan: ReadWorkflowPlan, result: ReadWorkflowResult
    ) -> WorkflowCritique:
        """Return a structured quality decision."""


class CapabilityResultProvider(Protocol):
    """Optional adapter boundary for callers that already enforce governance."""

    def results_for(
        self, plan: ReadWorkflowPlan
    ) -> Mapping[str, GovernedCapabilityResult]:
        """Return injected results; this protocol never accepts credentials."""


def planner_input(goal: str) -> dict[str, Any]:
    """Create the only input shape a planner needs."""

    return {"goal": goal}
