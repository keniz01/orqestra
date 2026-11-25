"""Planner and runner boundaries for governed read workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .contracts import (
    GovernedCapabilityResult,
    ReadWorkflowPlan,
    ReadWorkflowResult,
)


class ReadWorkflowPlanner(Protocol):
    """Produces typed intent only; it has no capability or credential access."""

    def plan(self, goal: str) -> ReadWorkflowPlan:
        """Return a model-independent plan for a user goal."""


class ReadWorkflowRunner(Protocol):
    """Consumes plans and injected governed results without executing them."""

    def run(
        self,
        plan: ReadWorkflowPlan,
        results: Sequence[GovernedCapabilityResult],
    ) -> ReadWorkflowResult:
        """Assemble a workflow result from already-governed capability results."""


class CapabilityResultProvider(Protocol):
    """Optional adapter boundary for callers that already enforce governance."""

    def results_for(
        self, plan: ReadWorkflowPlan
    ) -> Mapping[str, GovernedCapabilityResult]:
        """Return injected results; this protocol never accepts credentials."""


def planner_input(goal: str) -> dict[str, Any]:
    """Create the only input shape a planner needs."""

    return {"goal": goal}
