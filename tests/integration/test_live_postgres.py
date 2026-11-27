from __future__ import annotations

import asyncio
import os

import psycopg
import pytest

from connector_execution import (
    AsyncPostgresConnector,
    CancellationToken,
    ConnectorBinding,
    ConnectorIdentity,
)
from connector_execution.contracts import BoundExecutionRequest, ExecutionRequest
from execution_kernel import Principal


pytestmark = pytest.mark.live


def _dsn() -> str:
    value = os.environ.get("ORQESTRA_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("Docker PostgreSQL is not running for the live integration test.")
    return value


def test_real_postgres_connector_executes_read_only_query():
    dsn = _dsn()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS orqestra_live_revenue "
            "(id integer PRIMARY KEY, amount integer NOT NULL)"
        )
        connection.execute(
            "INSERT INTO orqestra_live_revenue (id, amount) VALUES (1, 42) "
            "ON CONFLICT (id) DO UPDATE SET amount = EXCLUDED.amount"
        )
        connection.commit()

    principal = Principal("live-user", "org-1", frozenset({"viewer"}))
    request = ExecutionRequest(
        principal,
        "analytics",
        "SELECT amount FROM orqestra_live_revenue ORDER BY id",
        max_rows=10,
    )
    bound = BoundExecutionRequest(
        request,
        ConnectorBinding(
            ConnectorIdentity("org-1", "analytics", "postgres"),
            dsn,
        ),
    )

    result = asyncio.run(
        AsyncPostgresConnector(statement_timeout_seconds=5).execute(
            bound, CancellationToken()
        )
    )

    assert result == ({"amount": 42},)


def test_real_postgres_connector_rejects_mutation():
    dsn = _dsn()
    principal = Principal("live-user", "org-1", frozenset({"viewer"}))
    request = ExecutionRequest(
        principal,
        "analytics",
        "DELETE FROM orqestra_live_revenue",
    )
    bound = BoundExecutionRequest(
        request,
        ConnectorBinding(
            ConnectorIdentity("org-1", "analytics", "postgres"),
            dsn,
        ),
    )

    with pytest.raises(ValueError):
        asyncio.run(
            AsyncPostgresConnector(statement_timeout_seconds=5).execute(
                bound, CancellationToken()
            )
        )
