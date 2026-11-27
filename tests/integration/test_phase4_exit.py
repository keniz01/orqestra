from __future__ import annotations

from datetime import timedelta

from execution_kernel import (
    ExecutionKernel,
    Principal,
    QueryPlan,
    RulePolicyEvaluator,
    TenantBinding,
    TenantBindingRegistry,
)
from control_api import GovernedReadControl, GoalRequest
from governed_orchestrator import (
    GovernedReadOrchestrator,
    GovernedReadWorkflowService,
    InMemoryWorkflowReportStore,
)
from governance import InMemoryGovernanceLedger
from read_workflows import (
    DeterministicReadWorkflowPlanner,
    GovernedContext,
    InMemoryReadWorkflowRunner,
    KernelCapabilityExecutor,
    KernelReadRequest,
)
from semantic_catalog import DataSourceMetadata, SourceKind
from task_runtime import InMemoryTaskStore
from workflow_reliability import (
    InMemoryCancellationStore,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
)


class Connector:
    def execute(self, binding, query, params):
        return [{"amount": 42}]


class ServerOwnedQueryBuilder:
    def build(self, principal, step):
        return KernelReadRequest(
            database_id="analytics",
            plan=QueryPlan("SELECT amount FROM revenue"),
        )


class ContextProvider:
    def build(self, principal, goal):
        return GovernedContext(
            tenant_id=principal.org_id,
            catalog=(
                DataSourceMetadata(
                    tenant_id=principal.org_id,
                    source_id="warehouse",
                    name="Analytics warehouse",
                    kind=SourceKind.WAREHOUSE,
                ),
            ),
        )


def test_phase4_read_workflow_completes_with_governance_and_replay():
    principal = Principal(
        user_id="user-1",
        org_id="org-1",
        roles=frozenset({"viewer"}),
    )
    kernel = ExecutionKernel(
        tenants=TenantBindingRegistry(
            {
                ("org-1", "analytics"): TenantBinding(
                    "org-1",
                    "analytics",
                    "warehouse",
                    "server-owned",
                )
            }
        ),
        policy=RulePolicyEvaluator(
            allow_rules=(
                {
                    "capability": "data.execute_read_query",
                    "org_id": "org-1",
                    "roles": ("viewer",),
                    "database_id": "analytics",
                    "tables": ("revenue",),
                },
            )
        ),
        executor=Connector(),
        audit_sink=lambda event: None,
    )
    capability_executor = KernelCapabilityExecutor(
        kernel,
        {
            "catalog.search_semantic_metadata": ServerOwnedQueryBuilder(),
            "data.plan_read_query": ServerOwnedQueryBuilder(),
        },
    )
    report_store = InMemoryWorkflowReportStore()
    orchestrator = GovernedReadOrchestrator(
        tasks=InMemoryTaskStore(),
        leases=InMemoryLeaseStore(),
        checkpoints=InMemoryCheckpointStore(),
        cancellations=InMemoryCancellationStore(),
        ledger=InMemoryGovernanceLedger(),
        executor=capability_executor,
        runner=InMemoryReadWorkflowRunner(),
        report_store=report_store,
        lease_ttl=timedelta(minutes=1),
    )
    service = GovernedReadWorkflowService(
        orchestrator,
        DeterministicReadWorkflowPlanner(),
    )
    control = GovernedReadControl(service, ContextProvider())

    response = control.submit(principal, GoalRequest("compare monthly revenue"))
    outcome = orchestrator.report_for(principal, response.trace_id)

    assert outcome is not None
    assert outcome.state.value == "completed"
    assert outcome.trace_id == response.trace_id
    assert outcome.query_hashes
    assert control.report_for(principal, response.trace_id) == outcome
