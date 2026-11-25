"""In-memory reference runner for governed read workflow contracts."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import (
    CapabilityResultState,
    GovernedCapabilityResult,
    ReadWorkflowPlan,
    ReadWorkflowResult,
    WorkflowResultState,
)


class InMemoryReadWorkflowRunner:
    """Assemble outcomes from injected results; never invokes capabilities."""

    def run(
        self,
        plan: ReadWorkflowPlan,
        results: Sequence[GovernedCapabilityResult],
    ) -> ReadWorkflowResult:
        if any(not isinstance(result, GovernedCapabilityResult) for result in results):
            raise TypeError("runner accepts only injected GovernedCapabilityResult values")
        by_step = {result.step_id: result for result in results}
        expected = {step.step_id: step for step in plan.steps}
        if len(by_step) != len(results):
            return ReadWorkflowResult(
                state=WorkflowResultState.BLOCKED,
                reason="Duplicate capability results are not accepted.",
            )
        if set(by_step) != set(expected):
            return ReadWorkflowResult(
                state=WorkflowResultState.BLOCKED,
                reason="Results must exactly match the planned steps.",
            )
        evidence_count = sum(len(result.evidence) for result in results)
        if evidence_count > plan.budget.max_evidence:
            return ReadWorkflowResult(
                state=WorkflowResultState.PARTIAL,
                reason="Capability evidence exceeds the workflow budget.",
            )
        if any(
            by_step[step_id].capability != step.capability
            for step_id, step in expected.items()
        ):
            return ReadWorkflowResult(
                state=WorkflowResultState.BLOCKED,
                reason="Capability results must match their planned steps.",
            )

        evidence = tuple(
            item
            for result in results
            for item in result.evidence
        )
        values = {result.step_id: result.value for result in results}
        failed = next(
            (
                result
                for result in results
                if result.state in {
                    CapabilityResultState.FAILED,
                    CapabilityResultState.DENIED,
                }
            ),
            None,
        )
        if failed is not None:
            return ReadWorkflowResult(
                state=(
                    WorkflowResultState.BLOCKED
                    if failed.state is CapabilityResultState.DENIED
                    else WorkflowResultState.FAILED
                ),
                values=values,
                evidence=evidence,
                reason=f"Capability result was {failed.state.value}.",
                query_hashes=tuple(
                    result.query_hash
                    for result in results
                    if result.query_hash is not None
                ),
            )
        if any(result.confidence is None for result in results):
            return ReadWorkflowResult(
                state=WorkflowResultState.PARTIAL,
                values=values,
                evidence=evidence,
                reason="Every capability result must provide confidence to complete.",
                query_hashes=tuple(
                    result.query_hash
                    for result in results
                    if result.query_hash is not None
                ),
            )
        confidence = min(result.confidence for result in results)
        if not evidence:
            return ReadWorkflowResult(
                state=WorkflowResultState.PARTIAL,
                values=values,
                confidence=confidence,
                reason="At least one provenance record is required to complete.",
                query_hashes=tuple(
                    result.query_hash
                    for result in results
                    if result.query_hash is not None
                ),
            )
        return ReadWorkflowResult(
            state=WorkflowResultState.COMPLETED,
            values=values,
            evidence=evidence,
            confidence=confidence,
            query_hashes=tuple(
                result.query_hash
                for result in results
                if result.query_hash is not None
            ),
        )
