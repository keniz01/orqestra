from __future__ import annotations

import asyncio

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
)
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
