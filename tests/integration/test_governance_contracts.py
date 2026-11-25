from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta

import pytest

from approval_plane import ApprovalDecision, ApprovalScopeError
from connector_execution import (
    BoundExecutionRequest,
    ConnectorResolutionError,
    ExecutionRequest,
    ExecutionTimeout,
)
from execution_kernel import (
    CapabilityRequest,
    PolicyDecisionResponse,
    PolicyServiceAdapter,
    Principal,
    QueryPlan,
)
from memory_service import (
    MemoryClassification,
    MemoryProvenance,
    MemoryRecord,
    MemoryRetention,
    MemoryScope,
    RetentionClass,
)
from read_workflows import (
    CapabilityResultState,
    Evidence,
    GovernedCapabilityResult,
    ReadPlanStep,
    ReadWorkflowPlan,
    WorkflowResultState,
)
from semantic_catalog import (
    CatalogPolicy,
    Classification,
    ColumnMetadata,
    DataSourceMetadata,
    Freshness,
    Provenance,
    SourceKind,
    TableMetadata,
)
from task_runtime import PlanStep, TaskStatus, TaskScopeError
from workflow_reliability import (
    CheckpointConflict,
    LeaseConflict,
    LeaseOwnershipError,
)

from .conftest import NOW, GovernanceHarness


def test_tenant_scoped_task_approval_and_ledger_lifecycle(
    governance_harness: GovernanceHarness,
) -> None:
    harness = governance_harness
    task = harness.tasks.create(
        harness.actor,
        "Investigate customer retention",
        [PlanStep("read", "data.execute_read_query")],
    )
    running = harness.tasks.transition(
        harness.actor, task.task_id, TaskStatus.RUNNING, expected_version=task.version
    )
    waiting = harness.tasks.transition(
        harness.actor,
        task.task_id,
        TaskStatus.WAITING_APPROVAL,
        expected_version=running.version,
    )
    request = harness.approvals.create(
        harness.actor,
        task_id=task.task_id,
        capability="data.execute_read_query",
        reason="Read customer retention data.",
        expires_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ApprovalScopeError):
        harness.approvals.decide(
            harness.actor,
            request.approval_id,
            ApprovalDecision.APPROVE,
            expected_version=request.version,
        )

    approved = harness.approvals.decide(
        harness.approver,
        request.approval_id,
        ApprovalDecision.APPROVE,
        expected_version=request.version,
    )
    assert harness.approvals.is_approved(
        harness.actor,
        approved.approval_id,
        task_id=task.task_id,
        capability="data.execute_read_query",
    )
    resumed = harness.tasks.transition(
        harness.actor,
        task.task_id,
        TaskStatus.RUNNING,
        expected_version=waiting.version,
    )
    completed = harness.tasks.transition(
        harness.actor,
        task.task_id,
        TaskStatus.COMPLETED,
        expected_version=resumed.version,
    )

    assert completed.status is TaskStatus.COMPLETED
    assert [
        event.event_type
        for event in harness.ledger.events_for(harness.actor, task_id=task.task_id)
    ] == [
        "task.created",
        "task.transitioned",
        "task.transitioned",
        "approval.created",
        "approval.decided",
        "task.transitioned",
        "task.transitioned",
    ]
    with pytest.raises(TaskScopeError):
        harness.tasks.get(harness.other_tenant, task.task_id)
    assert harness.ledger.events_for(harness.other_tenant, task_id=task.task_id) == ()


def test_policy_is_fail_closed_and_connector_credentials_are_rejected(
    governance_harness: GovernanceHarness,
) -> None:
    request = CapabilityRequest(
        principal=governance_harness.actor,
        capability="data.execute_read_query",
        database_id="analytics",
    )

    class UnavailablePolicy:
        def decide(self, request: CapabilityRequest) -> PolicyDecisionResponse:
            raise ConnectionError("unavailable")

    decision = PolicyServiceAdapter(UnavailablePolicy()).evaluate(request)
    assert decision.allowed is False

    with pytest.raises(ValueError, match="credential-bearing"):
        ExecutionRequest(
            principal=governance_harness.actor,
            database_id="analytics",
            statement="SELECT 1",
            parameters={"nested": {"api_token": "must-not-cross-boundary"}},
        )

    class Connector:
        async def execute(self, request: BoundExecutionRequest, cancellation):
            return [{"ok": True}]

    with pytest.raises(ConnectorResolutionError):
        asyncio.run(
            governance_harness.connectors.run(
                ExecutionRequest(
                    principal=governance_harness.other_tenant,
                    database_id="analytics",
                    statement="SELECT 1",
                ),
                Connector(),
                timeout=ExecutionTimeout(1),
            )
        )


def test_workflow_lease_and_checkpoint_contracts_are_optimistic(
    governance_harness: GovernanceHarness,
) -> None:
    lease = governance_harness.leases.acquire(
        "task-workflow", "worker-1", timedelta(seconds=10), now=NOW
    )
    with pytest.raises(LeaseConflict):
        governance_harness.leases.acquire(
            "task-workflow", "worker-2", timedelta(seconds=10), now=NOW
        )
    renewed = governance_harness.leases.renew(
        "task-workflow",
        lease.lease_id,
        "worker-1",
        timedelta(seconds=10),
        now=NOW + timedelta(seconds=5),
    )
    assert renewed.version == 1
    with pytest.raises(LeaseOwnershipError):
        governance_harness.leases.renew(
            "task-workflow",
            renewed.lease_id,
            "worker-2",
            timedelta(seconds=10),
            now=NOW,
        )

    first = governance_harness.checkpoints.save("task-workflow", {"step": "read"}, now=NOW)
    second = governance_harness.checkpoints.save(
        "task-workflow",
        {"step": "assemble"},
        expected_version=first.version,
        now=NOW + timedelta(seconds=1),
    )
    assert second.version == 2
    with pytest.raises(CheckpointConflict):
        governance_harness.checkpoints.save(
            "task-workflow",
            {"step": "stale"},
            expected_version=first.version,
            now=NOW + timedelta(seconds=2),
        )


def test_catalog_and_memory_reads_are_tenant_and_policy_filtered(
    governance_harness: GovernanceHarness,
) -> None:
    source = DataSourceMetadata(
        tenant_id="org-1",
        source_id="warehouse",
        name="Warehouse",
        kind=SourceKind.WAREHOUSE,
        classification=Classification.PUBLIC,
        provenance=Provenance("scanner", "warehouse", NOW, "catalog-job"),
        freshness=Freshness(NOW, timedelta(hours=1)),
        tables=(
            TableMetadata(
                tenant_id="org-1",
                source_id="warehouse",
                table_id="customers",
                name="Customers",
                classification=Classification.PUBLIC,
                columns=(
                    ColumnMetadata(
                        tenant_id="org-1",
                        source_id="warehouse",
                        table_id="customers",
                        name="id",
                        data_type="uuid",
                        classification=Classification.PUBLIC,
                    ),
                    ColumnMetadata(
                        tenant_id="org-1",
                        source_id="warehouse",
                        table_id="customers",
                        name="email",
                        data_type="text",
                        classification=Classification.CONFIDENTIAL,
                    ),
                ),
            ),
        ),
    )
    governance_harness.catalog.register(source)
    visible = governance_harness.catalog.read(
        governance_harness.actor,
        CatalogPolicy(max_classification=Classification.PUBLIC),
    )
    assert [column.name for column in visible[0].tables[0].columns] == ["id"]
    assert governance_harness.catalog.read(governance_harness.other_tenant) == ()

    memory = MemoryRecord(
        org_id="org-1",
        scope=MemoryScope.TENANT,
        scope_id="tenant",
        content="Verified governed observation.",
        classification=MemoryClassification.INTERNAL,
        retention=MemoryRetention(RetentionClass.STANDARD),
        provenance=MemoryProvenance(
            "task_observation", "task-1", "analyst-1", "Verified observation."
        ),
        created_at=NOW,
    )
    governance_harness.memory.write(governance_harness.actor, memory)
    assert governance_harness.memory.retrieve(governance_harness.actor) == (memory,)
    assert governance_harness.memory.retrieve(governance_harness.other_tenant) == ()


def test_governed_read_results_carry_execution_evidence(
    governance_harness: GovernanceHarness,
) -> None:
    task_id = "task-read-1"
    plan = QueryPlan("SELECT id, email FROM customers")
    result = governance_harness.kernel.execute(
        principal=governance_harness.actor,
        database_id="analytics",
        plan=plan,
        task_id=task_id,
    )
    assert result.rows == ({"id": "customer-1", "email": None},)

    query_hash = hashlib.sha256(plan.sql.encode("utf-8")).hexdigest()
    workflow_result = governance_harness.read_workflows.run(
        ReadWorkflowPlan(
            goal="Read governed customer facts",
            steps=(ReadPlanStep("read", "data.execute_read_query"),),
        ),
        (
            GovernedCapabilityResult(
                step_id="read",
                capability="data.execute_read_query",
                state=CapabilityResultState.SUCCEEDED,
                value={"rows": result.rows},
                evidence=(
                    Evidence(
                        source="execution-kernel",
                        reference=f"query:{query_hash}",
                        capability="data.execute_read_query",
                        observed_at=NOW,
                        metadata={"task_id": task_id, "tenant_id": "org-1"},
                    ),
                ),
                confidence=1.0,
            ),
        ),
    )

    assert workflow_result.state is WorkflowResultState.COMPLETED
    assert workflow_result.evidence[0].reference == f"query:{query_hash}"
    assert [
        event.event_type
        for event in governance_harness.ledger.events_for(
            governance_harness.actor, task_id=task_id
        )
    ] == ["kernel.capability_decision", "kernel.capability_executed"]
