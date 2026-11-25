from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest

from approval_plane import ApprovalStore
from connector_execution import (
    AsyncConnectorRunner,
    ConnectorBinding,
    ConnectorBindingRegistry,
    ConnectorIdentity,
)
from execution_kernel import (
    AuditEvent,
    ExecutionKernel,
    Principal,
    QueryPlan,
    RulePolicyEvaluator,
    TenantBinding,
    TenantBindingRegistry,
)
from governance import GovernanceEvent, InMemoryGovernanceLedger
from memory_service import InMemoryMemoryStore
from read_workflows import InMemoryReadWorkflowRunner
from semantic_catalog import InMemorySemanticCatalog
from task_runtime import InMemoryTaskStore
from workflow_reliability import InMemoryCheckpointStore, InMemoryLeaseStore


NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


class FixtureQueryExecutor:
    def execute(
        self,
        binding: TenantBinding,
        query: Any,
        params: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        assert binding.org_id == "org-1"
        assert binding.database_id == "analytics"
        return ({"id": "customer-1", "email": "customer@example.test"},)


@dataclass
class GovernanceHarness:
    actor: Principal
    approver: Principal
    other_tenant: Principal
    ledger: InMemoryGovernanceLedger
    tasks: InMemoryTaskStore
    approvals: ApprovalStore
    kernel: ExecutionKernel
    connectors: AsyncConnectorRunner
    catalog: InMemorySemanticCatalog
    memory: InMemoryMemoryStore
    leases: InMemoryLeaseStore
    checkpoints: InMemoryCheckpointStore
    read_workflows: InMemoryReadWorkflowRunner


@pytest.fixture
def governance_harness() -> GovernanceHarness:
    actor = Principal("analyst-1", "org-1", frozenset({"analyst"}))
    approver = Principal("approver-1", "org-1", frozenset({"approver"}))
    other_tenant = Principal("analyst-2", "org-2", frozenset({"analyst"}))
    ledger = InMemoryGovernanceLedger()

    def record(event: GovernanceEvent) -> None:
        ledger.append(event)

    tasks = InMemoryTaskStore(event_sink=record)
    approvals = ApprovalStore(event_sink=record)

    def record_audit(event: AuditEvent) -> None:
        record(
            GovernanceEvent(
                org_id=event.org_id,
                event_type=f"kernel.{event.event_type}",
                actor_user_id=event.user_id,
                decision=event.decision,
                reason=event.reason,
                task_id=event.task_id,
                capability=event.capability,
                payload={"database_id": event.database_id, "query_hash": event.query_hash},
                occurred_at=event.occurred_at,
            )
        )

    kernel = ExecutionKernel(
        tenants=TenantBindingRegistry(
            {
                ("org-1", "analytics"): TenantBinding(
                    "org-1", "analytics", "warehouse-1", "server-owned-target"
                )
            }
        ),
        policy=RulePolicyEvaluator(
            allow_rules=(
                {
                    "capability": "data.execute_read_query",
                    "org_id": "org-1",
                    "roles": ("analyst",),
                    "database_id": "analytics",
                    "tables": ("customers",),
                    "masked_columns": ("email",),
                },
            )
        ),
        executor=FixtureQueryExecutor(),
        audit_sink=record_audit,
    )
    connectors = AsyncConnectorRunner(
        ConnectorBindingRegistry(
            {
                ("org-1", "analytics"): ConnectorBinding(
                    ConnectorIdentity("org-1", "analytics", "warehouse-1"),
                    "server-owned-target",
                )
            }
        )
    )

    return GovernanceHarness(
        actor=actor,
        approver=approver,
        other_tenant=other_tenant,
        ledger=ledger,
        tasks=tasks,
        approvals=approvals,
        kernel=kernel,
        connectors=connectors,
        catalog=InMemorySemanticCatalog(),
        memory=InMemoryMemoryStore(),
        leases=InMemoryLeaseStore(),
        checkpoints=InMemoryCheckpointStore(),
        read_workflows=InMemoryReadWorkflowRunner(),
    )
