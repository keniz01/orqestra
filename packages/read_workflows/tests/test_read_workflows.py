from __future__ import annotations

import pytest

from read_workflows import (
    CapabilityResultState,
    Evidence,
    GovernedCapabilityResult,
    InMemoryReadWorkflowRunner,
    ReadPlanStep,
    ReadWorkflowPlan,
    ReadWorkflowReport,
    ReadWorkflowResult,
    WorkflowBudget,
    WorkflowCritique,
    CritiqueState,
    WorkflowResultState,
)


def plan() -> ReadWorkflowPlan:
    return ReadWorkflowPlan(
        goal="Compare monthly revenue",
        steps=(ReadPlanStep("aggregate", "catalog.metric", {"metric": "revenue"}),),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"sql": "SELECT * FROM customers"},
        {"credentials": {"password": "not-a-secret"}},
        {"nested": [{"connection_string": "server-owned"}]},
    ],
)
def test_plan_rejects_direct_sql_and_credential_inputs(arguments):
    with pytest.raises(ValueError):
        ReadPlanStep("step-1", "data.read", arguments)


def test_runner_only_assembles_injected_governed_results():
    result = InMemoryReadWorkflowRunner().run(
        plan(),
        (
            GovernedCapabilityResult(
                step_id="aggregate",
                capability="catalog.metric",
                state=CapabilityResultState.SUCCEEDED,
                value={"amount": 42},
                evidence=(
                    Evidence(
                        source="metric-catalog",
                        reference="metric:revenue:2026-10",
                        capability="catalog.metric",
                    ),
                ),
                confidence=0.9,
            ),
        ),
    )

    assert result.state is WorkflowResultState.COMPLETED
    assert result.confidence == 0.9
    assert result.evidence[0].reference == "metric:revenue:2026-10"


def test_completion_requires_evidence_and_confidence():
    with pytest.raises(ValueError, match="evidence"):
        ReadWorkflowResult(state=WorkflowResultState.COMPLETED, confidence=0.9)
    with pytest.raises(ValueError, match="confidence"):
        ReadWorkflowResult(
            state=WorkflowResultState.COMPLETED,
            evidence=(
                Evidence(
                    source="catalog",
                    reference="record-1",
                    capability="catalog.metric",
                ),
            ),
        )

    incomplete = InMemoryReadWorkflowRunner().run(
        plan(),
        (
            GovernedCapabilityResult(
                step_id="aggregate",
                capability="catalog.metric",
                state=CapabilityResultState.SUCCEEDED,
            ),
        ),
    )
    assert incomplete.state is WorkflowResultState.PARTIAL


def test_plan_budget_and_report_preserve_replay_metadata():
    bounded = ReadWorkflowPlan(
        goal="Compare revenue",
        steps=(ReadPlanStep("aggregate", "catalog.metric"),),
        budget=WorkflowBudget(max_steps=1, max_evidence=1),
    )
    result = InMemoryReadWorkflowRunner().run(
        bounded,
        (
            GovernedCapabilityResult(
                step_id="aggregate",
                capability="catalog.metric",
                state=CapabilityResultState.SUCCEEDED,
                evidence=(
                    Evidence(
                        "catalog",
                        "metric:revenue",
                        "catalog.metric",
                        query_hash="hash-1",
                    ),
                ),
                confidence=0.8,
                query_hash="hash-1",
            ),
        ),
    )

    report = ReadWorkflowReport.from_result(
        bounded.goal, result, trace_id="task-1"
    )
    assert result.state is WorkflowResultState.COMPLETED
    assert report.trace_id == "task-1"
    assert report.citations == ("metric:revenue",)
    assert report.query_hashes == ("hash-1",)


def test_non_accepted_critique_prevents_completion():
    result = ReadWorkflowResult(
        state=WorkflowResultState.PARTIAL,
        critique=WorkflowCritique(
            state=CritiqueState.NEEDS_REVIEW,
            reason="The result needs analyst review.",
        ),
    )
    assert result.state is WorkflowResultState.PARTIAL
