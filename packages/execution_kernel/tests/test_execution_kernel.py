from __future__ import annotations

import pytest

from execution_kernel import (
    CapabilityRegistry,
    CapabilitySpec,
    DelegationContext,
    ExecutionKernel,
    ExecutionLimits,
    Principal,
    QueryPlan,
    RulePolicyEvaluator,
    TenantBinding,
    TenantBindingRegistry,
    SqlValidationError,
    validate_read_query,
)
from datetime import datetime, timedelta, timezone


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, binding, query, params):
        self.calls.append((binding, query, params))
        return [
            {"id": 1, "email": "one@example.test"},
            {"id": 2, "email": "two@example.test"},
            {"id": 3, "email": "three@example.test"},
        ]


def make_principal() -> Principal:
    return Principal(
        user_id="user-1",
        org_id="org-1",
        roles=frozenset({"viewer"}),
    )


def make_kernel(audit_events, executor=None):
    executor = executor or FakeExecutor()
    tenants = TenantBindingRegistry(
        {
            ("org-1", "analytics"): TenantBinding(
                org_id="org-1",
                database_id="analytics",
                connector_id="postgres-primary",
                target="server-owned-target",
            )
        }
    )
    policy = RulePolicyEvaluator(
        allow_rules=(
            {
                "capability": "data.execute_read_query",
                "org_id": "org-1",
                "roles": ("viewer",),
                "database_id": "analytics",
                "tables": ("customers",),
                "masked_columns": ("email",),
            },
        )
    )
    return (
        ExecutionKernel(
            tenants=tenants,
            policy=policy,
            executor=executor,
            audit_sink=audit_events.append,
            limits=ExecutionLimits(max_rows=2),
        ),
        executor,
    )


def test_kernel_resolves_tenant_authorizes_masks_and_bounds_results():
    events = []
    kernel, executor = make_kernel(events)

    result = kernel.execute(
        principal=make_principal(),
        database_id="analytics",
        plan=QueryPlan("SELECT id, email FROM customers"),
        task_id="task-1",
    )

    assert result.rows == ({"id": 1, "email": None}, {"id": 2, "email": None})
    assert result.truncated is True
    assert result.result_bytes > 0
    assert executor.calls[0][0].target == "server-owned-target"
    assert [event.event_type for event in events] == [
        "capability_decision",
        "capability_executed",
    ]


def test_kernel_denies_unmatched_policy_before_executor():
    events = []
    kernel, executor = make_kernel(events)

    with pytest.raises(PermissionError, match="No allow policy"):
        kernel.execute(
            principal=make_principal(),
            database_id="analytics",
            plan=QueryPlan("SELECT id FROM secrets"),
        )

    assert executor.calls == []
    assert events[0].decision == "deny"


def test_delegation_scopes_agent_to_registered_capability_and_task():
    events = []
    kernel, executor = make_kernel(events)
    delegation = DelegationContext(
        agent_id="analyst-agent",
        task_id="task-42",
        allowed_capabilities=frozenset({"data.execute_read_query"}),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    result = kernel.execute(
        principal=make_principal(),
        database_id="analytics",
        plan=QueryPlan("SELECT id FROM customers"),
        delegation=delegation,
    )

    assert result.rows
    assert events[0].agent_id == "analyst-agent"
    assert events[0].task_id == "task-42"


def test_expired_delegation_cannot_execute():
    events = []
    kernel, executor = make_kernel(events)
    delegation = DelegationContext(
        agent_id="analyst-agent",
        task_id="task-42",
        allowed_capabilities=frozenset({"data.execute_read_query"}),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(PermissionError, match="does not authorize"):
        kernel.execute(
            principal=make_principal(),
            database_id="analytics",
            plan=QueryPlan("SELECT id FROM customers"),
            delegation=delegation,
        )

    assert executor.calls == []


def test_registry_rejects_duplicate_capabilities():
    registry = CapabilityRegistry()
    capability = CapabilitySpec(
        name="data.execute_read_query",
        description="Read data",
        read_only=True,
    )
    registry.register(capability)

    with pytest.raises(PermissionError, match="already registered"):
        registry.register(capability)


def test_kernel_rejects_cross_tenant_database_resolution():
    events = []
    kernel, executor = make_kernel(events)
    other_tenant = Principal(user_id="user-2", org_id="org-2", roles=frozenset({"viewer"}))

    with pytest.raises(PermissionError, match="not available"):
        kernel.execute(
            principal=other_tenant,
            database_id="analytics",
            plan=QueryPlan("SELECT id FROM customers"),
        )

    assert executor.calls == []
    assert events[0].decision == "deny"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE customers SET email = 'x'",
        "SELECT pg_sleep(10) FROM customers",
        "SELECT * FROM information_schema.tables",
        "SELECT id FROM customers; SELECT id FROM orders",
        "SELECT id FROM customers -- comment",
    ],
)
def test_read_validator_rejects_unsafe_queries(sql):
    with pytest.raises(SqlValidationError):
        validate_read_query(sql)
