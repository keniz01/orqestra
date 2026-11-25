from __future__ import annotations

import pytest

from execution_kernel import (
    ExecutionKernel,
    Principal,
    QueryPlan,
    RulePolicyEvaluator,
    TenantBinding,
    TenantBindingRegistry,
)
from read_workflows import (
    KernelCapabilityExecutor,
    KernelReadRequest,
    ReadPlanStep,
)


class Executor:
    def execute(self, binding, query, params):
        return [{"amount": 42}]


class Builder:
    def build(self, principal, step):
        return KernelReadRequest(
            database_id="analytics",
            plan=QueryPlan("SELECT amount FROM revenue"),
        )


def kernel(allow: bool) -> ExecutionKernel:
    return ExecutionKernel(
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
                (
                    {
                        "capability": "data.execute_read_query",
                        "org_id": "org-1",
                        "roles": ("viewer",),
                        "database_id": "analytics",
                        "tables": ("revenue",),
                    },
                )
                if allow
                else ()
            )
        ),
        executor=Executor(),
        audit_sink=lambda event: None,
    )


def test_kernel_executor_materializes_server_owned_query_and_provenance():
    executor = KernelCapabilityExecutor(
        kernel(True),
        {"data.plan_read_query": Builder()},
    )

    result = executor.execute(
        Principal(user_id="user-1", org_id="org-1", roles=frozenset({"viewer"})),
        "task-1",
        ReadPlanStep("read", "data.plan_read_query", {"goal": "revenue"}),
    )

    assert result.value == ({"amount": 42},)
    assert result.query_hash
    assert result.evidence[0].reference == f"query:{result.query_hash}"


def test_kernel_executor_remains_fail_closed_on_policy_denial():
    executor = KernelCapabilityExecutor(
        kernel(False),
        {"data.plan_read_query": Builder()},
    )

    with pytest.raises(PermissionError):
        executor.execute(
            Principal(user_id="user-1", org_id="org-1"),
            "task-1",
            ReadPlanStep("read", "data.plan_read_query", {"goal": "revenue"}),
        )
