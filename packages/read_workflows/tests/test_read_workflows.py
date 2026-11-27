from __future__ import annotations

import pytest

from read_workflows import (
    CapabilityResultState,
    AllowlistedPlanProvider,
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
    DeterministicReadWorkflowPlanner,
    GovernedContext,
    ModelReadWorkflowPlanner,
    PlanProvenance,
    WorkflowResultState,
)
from execution_kernel import Principal


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


def test_deterministic_planner_emits_typed_intent_only():
    principal = Principal(user_id="user-1", org_id="org-1")
    plan = DeterministicReadWorkflowPlanner().plan_for(
        principal,
        "compare monthly revenue",
        GovernedContext(tenant_id="org-1"),
    )

    assert plan.steps[0].capability == "catalog.search_semantic_metadata"
    assert "sql" not in plan.steps[0].arguments
    assert "credentials" not in plan.steps[0].arguments


def test_planner_rejects_cross_tenant_context():
    with pytest.raises(PermissionError, match="tenant boundary"):
        DeterministicReadWorkflowPlanner().plan_for(
            Principal(user_id="user-1", org_id="org-1"),
            "read revenue",
            GovernedContext(tenant_id="org-2"),
        )


class _TypedGenerator:
    def __init__(self, value):
        self.value = value

    def generate(self, principal, goal, context):
        return self.value(principal, goal, context) if callable(self.value) else self.value


def _model_planner(generator, *, model="model-v1", capabilities=frozenset({"catalog.metric"})):
    return ModelReadWorkflowPlanner(
        AllowlistedPlanProvider(
            provider="test-provider",
            model=model,
            prompt_version="prompt-v1",
            generators={model: _TypedGenerator(generator)},
            allowed_capabilities=capabilities,
        )
    )


def test_model_planner_records_provider_model_and_context_references():
    principal = Principal(user_id="user-1", org_id="org-1")
    context = GovernedContext(tenant_id="org-1")
    planner = _model_planner(
        ReadWorkflowPlan(
            goal="read revenue",
            steps=(ReadPlanStep("read", "catalog.metric"),),
        )
    )

    planned = planner.plan_for(principal, "read revenue", context)

    assert planned.provenance == PlanProvenance(
        provider="test-provider",
        model="model-v1",
        prompt_version="prompt-v1",
    )


def test_model_planner_rejects_unallowlisted_model():
    provider = AllowlistedPlanProvider(
        provider="test-provider",
        model="missing",
        prompt_version="prompt-v1",
        generators={"model-v1": _TypedGenerator(plan())},
        allowed_capabilities=frozenset({"catalog.metric"}),
    )

    with pytest.raises(PermissionError, match="allowlisted"):
        provider.plan(
            Principal(user_id="user-1", org_id="org-1"),
            "Compare monthly revenue",
            GovernedContext(tenant_id="org-1"),
        )


def test_model_planner_rejects_untyped_and_unauthorized_output():
    principal = Principal(user_id="user-1", org_id="org-1")
    context = GovernedContext(tenant_id="org-1")

    with pytest.raises(TypeError, match="typed"):
        _model_planner("not a plan").plan_for(principal, "read revenue", context)

    unauthorized = ReadWorkflowPlan(
        goal="read revenue",
        steps=(ReadPlanStep("read", "data.execute_write"),),
    )
    with pytest.raises(PermissionError, match="allowlist"):
        _model_planner(unauthorized).plan_for(principal, "read revenue", context)


def test_model_planner_rejects_goal_mismatch_and_budget_overrun():
    principal = Principal(user_id="user-1", org_id="org-1")
    context = GovernedContext(tenant_id="org-1")
    mismatch = ReadWorkflowPlan(
        goal="different goal",
        steps=(ReadPlanStep("read", "catalog.metric"),),
    )
    with pytest.raises(ValueError, match="goal"):
        _model_planner(mismatch).plan_for(principal, "read revenue", context)

    two_steps = ReadWorkflowPlan(
        goal="read revenue",
        steps=(
            ReadPlanStep("one", "catalog.metric"),
            ReadPlanStep("two", "catalog.metric"),
        ),
    )
    with pytest.raises(ValueError, match="budget"):
        _model_planner(two_steps).plan_for(
            principal,
            "read revenue",
            context,
            budget=WorkflowBudget(max_steps=1),
        )
