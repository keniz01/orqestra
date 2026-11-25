from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from connector_execution import (
    AsyncConnectorRunner,
    BoundExecutionRequest,
    CancellationToken,
    ConnectorBinding,
    ConnectorBindingRegistry,
    ConnectorCancelledError,
    ConnectorIdentity,
    ConnectorResolutionError,
    ConnectorTimeoutError,
    ExecutionRequest,
    ExecutionTimeout,
    GovernedConnectorRunner,
)
from execution_kernel import PolicyDecision, DecisionProvenance
from execution_kernel import Principal


def make_request(**kwargs) -> ExecutionRequest:
    return ExecutionRequest(
        principal=Principal(user_id="user-1", org_id="org-1"),
        database_id="analytics",
        statement="SELECT id FROM customers",
        **kwargs,
    )


def make_runner() -> AsyncConnectorRunner:
    return AsyncConnectorRunner(
        ConnectorBindingRegistry(
            {
                ("org-1", "analytics"): ConnectorBinding(
                    identity=ConnectorIdentity("org-1", "analytics", "postgres-1"),
                    target="server-owned-target",
                )
            }
        )
    )


class RowsConnector:
    async def execute(self, request: BoundExecutionRequest, cancellation: CancellationToken):
        return [{"id": 1}, {"id": 2}, {"id": 3}]


def test_runner_resolves_server_owned_tenant_database_binding_and_bounds_results():
    result = asyncio.run(
        make_runner().run(
            make_request(max_rows=2),
            RowsConnector(),
            timeout=ExecutionTimeout(1),
        )
    )

    assert result.rows == ({"id": 1}, {"id": 2})
    assert result.truncated is True


def test_cross_tenant_database_binding_is_rejected():
    request = ExecutionRequest(
        principal=Principal(user_id="user-1", org_id="org-2"),
        database_id="analytics",
        statement="SELECT 1",
    )

    with pytest.raises(ConnectorResolutionError):
        asyncio.run(
            make_runner().run(request, RowsConnector(), timeout=ExecutionTimeout(1))
        )


def test_cancellation_stops_connector():
    async def scenario():
        token = CancellationToken()

        class SlowConnector:
            async def execute(self, request, cancellation):
                await asyncio.sleep(10)
                return []

        task = asyncio.create_task(
            make_runner().run(
                make_request(), SlowConnector(), timeout=ExecutionTimeout(5), cancellation=token
            )
        )
        await asyncio.sleep(0)
        token.cancel()
        with pytest.raises(ConnectorCancelledError):
            await task

    asyncio.run(scenario())


def test_timeout_stops_connector():
    async def scenario():
        class SlowConnector:
            async def execute(self, request, cancellation):
                await asyncio.sleep(10)
                return []

        with pytest.raises(ConnectorTimeoutError):
            await make_runner().run(
                make_request(), SlowConnector(), timeout=ExecutionTimeout(0.001)
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "parameters",
    [
        {"password": "not-allowed"},
        {"nested": {"api_key": "not-allowed"}},
        {"items": [{"client_secret": "not-allowed"}]},
    ],
)
def test_credential_bearing_inputs_are_rejected(parameters):
    with pytest.raises(ValueError, match="credential-bearing"):
        make_request(parameters=parameters)


def make_governed_runner(policy, events):
    return GovernedConnectorRunner(
        policy=policy,
        bindings=ConnectorBindingRegistry(
            {
                ("org-1", "analytics"): ConnectorBinding(
                    identity=ConnectorIdentity("org-1", "analytics", "postgres-1"),
                    target="server-owned-target",
                )
            }
        ),
        audit_sink=events.append,
    )


class AllowConnector:
    async def execute(self, request, cancellation):
        assert request.binding.identity.connector_id == "postgres-1"
        return [{"id": 1}, {"id": 2}, {"id": 3}]


class StaticPolicy:
    def __init__(self, decision):
        self.decision = decision

    def evaluate(self, request):
        return self.decision(request) if callable(self.decision) else self.decision


def test_governed_runner_requires_policy_allow_and_emits_attributable_events():
    events = []
    policy = StaticPolicy(PolicyDecision(True, "Allowed by policy."))
    result = asyncio.run(
        make_governed_runner(policy, events).run(
            make_request(max_rows=2, task_id="task-1"),
            AllowConnector(),
            timeout=ExecutionTimeout(1),
        )
    )

    assert result.rows == ({"id": 1}, {"id": 2})
    assert result.truncated is True
    assert events[0].org_id == "org-1"
    assert events[0].user_id == "user-1"
    assert events[0].task_id == "task-1"
    assert events[-1].event_type == "capability_executed"
    assert events[-1].payload["truncated"] is True


def test_governed_runner_denies_without_calling_connector():
    events = []
    called = False

    class NeverConnector:
        async def execute(self, request, cancellation):
            nonlocal called
            called = True
            return []

    with pytest.raises(PermissionError, match="Denied"):
        asyncio.run(
            make_governed_runner(
                StaticPolicy(PolicyDecision(False, "Denied by policy.")), events
            ).run(make_request(), NeverConnector(), timeout=ExecutionTimeout(1))
        )
    assert called is False
    assert events[-1].decision == "deny"


def test_governed_runner_fails_closed_when_policy_is_unavailable():
    events = []

    def unavailable(request):
        raise ConnectionError("down")

    with pytest.raises(PermissionError, match="unavailable"):
        asyncio.run(
            make_governed_runner(StaticPolicy(unavailable), events).run(
                make_request(), AllowConnector(), timeout=ExecutionTimeout(1)
            )
        )
    assert events[-1].decision == "deny"


def test_governed_runner_rejects_policy_tenant_mismatch():
    events = []
    decision = PolicyDecision(
        True,
        "allowed",
        provenance=DecisionProvenance(
            source="test",
            policy_version="v1",
            decision_id="d1",
            evaluated_at=datetime.now(timezone.utc),
            tenant_id="org-other",
        ),
    )
    with pytest.raises(PermissionError, match="tenant mismatch"):
        asyncio.run(
            make_governed_runner(StaticPolicy(decision), events).run(
                make_request(), AllowConnector(), timeout=ExecutionTimeout(1)
            )
        )


def test_governed_runner_propagates_cancellation_and_timeout():
    events = []

    class SlowConnector:
        async def execute(self, request, cancellation):
            await asyncio.sleep(10)
            return []

    async def scenario():
        token = CancellationToken()
        task = asyncio.create_task(
            make_governed_runner(StaticPolicy(PolicyDecision(True, "allowed")), events).run(
                make_request(),
                SlowConnector(),
                timeout=ExecutionTimeout(5),
                cancellation=token,
            )
        )
        await asyncio.sleep(0)
        token.cancel()
        with pytest.raises(ConnectorCancelledError):
            await task
        with pytest.raises(ConnectorTimeoutError):
            await make_governed_runner(
                StaticPolicy(PolicyDecision(True, "allowed")), events
            ).run(make_request(), SlowConnector(), timeout=ExecutionTimeout(0.001))

    asyncio.run(scenario())
