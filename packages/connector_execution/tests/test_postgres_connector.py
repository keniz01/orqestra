from __future__ import annotations

import asyncio

import pytest

from connector_execution import (
    AsyncPostgresConnector,
    CancellationToken,
    ConnectorBinding,
    ConnectorIdentity,
)
from connector_execution.contracts import BoundExecutionRequest, ExecutionRequest
from execution_kernel import Principal


class Cursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def execute(self, query, params=None):
        self.statements.append((query, params))

    async def fetchmany(self, size):
        assert size == 3
        return [{"amount": 42}]


class Connection:
    def __init__(self) -> None:
        self.cursor_instance = Cursor()
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def rollback(self):
        self.rolled_back = True

    async def close(self):
        self.closed = True


class Factory:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.target = None

    async def connect(self, target, *, connect_timeout):
        self.target = (target, connect_timeout)
        return self.connection


def test_postgres_connector_enforces_read_only_session_and_server_binding():
    connection = Connection()
    factory = Factory(connection)
    connector = AsyncPostgresConnector(factory, statement_timeout_seconds=2)
    request = ExecutionRequest(
        Principal("user-1", "org-1", frozenset({"viewer"})),
        "analytics",
        "SELECT amount FROM revenue",
        max_rows=2,
    )
    bound = BoundExecutionRequest(
        request,
        ConnectorBinding(
            ConnectorIdentity("org-1", "analytics", "postgres"),
            "postgresql://server-owned",
        ),
    )

    result = asyncio.run(connector.execute(bound, CancellationToken()))

    assert result == ({"amount": 42},)
    assert factory.target == ("postgresql://server-owned", 2)
    assert connection.rolled_back is True
    assert connection.closed is True
    assert connection.cursor_instance.statements == [
        ("SET TRANSACTION READ ONLY", None),
        ("SET LOCAL statement_timeout = '2000ms'", None),
        ("SELECT amount FROM revenue", {}),
    ]


def test_postgres_connector_rejects_non_read_query_before_connecting():
    factory = Factory(Connection())
    connector = AsyncPostgresConnector(factory)
    request = ExecutionRequest(
        Principal("user-1", "org-1", frozenset({"viewer"})),
        "analytics",
        "DELETE FROM revenue",
    )
    bound = BoundExecutionRequest(
        request,
        ConnectorBinding(
            ConnectorIdentity("org-1", "analytics", "postgres"),
            "postgresql://server-owned",
        ),
    )

    with pytest.raises(ValueError):
        asyncio.run(connector.execute(bound, CancellationToken()))
    assert factory.target is None
