"""PostgreSQL adapter with defense-in-depth read-only enforcement."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from execution_kernel import validate_read_query

from .contracts import BoundExecutionRequest, CancellationToken


class AsyncPostgresCursor(Protocol):
    async def execute(self, query: str, params: Mapping[str, Any] | None = None) -> None:
        ...

    async def fetchmany(self, size: int) -> list[Mapping[str, Any]]:
        ...

    async def __aenter__(self) -> "AsyncPostgresCursor":
        ...

    async def __aexit__(self, *exc_info: object) -> None:
        ...


class AsyncPostgresConnection(Protocol):
    def cursor(self) -> AsyncPostgresCursor:
        ...

    async def rollback(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def __aenter__(self) -> "AsyncPostgresConnection":
        ...

    async def __aexit__(self, *exc_info: object) -> None:
        ...


class AsyncPostgresConnectionFactory(Protocol):
    async def connect(
        self, target: str, *, connect_timeout: float
    ) -> AsyncPostgresConnection:
        ...


class AsyncPostgresConnector:
    """Execute one server-bound statement in a read-only PostgreSQL session."""

    def __init__(
        self,
        connection_factory: AsyncPostgresConnectionFactory | None = None,
        *,
        statement_timeout_seconds: float = 30,
    ) -> None:
        if statement_timeout_seconds <= 0:
            raise ValueError("statement_timeout_seconds must be positive")
        self._factory = connection_factory or _PsycopgConnectionFactory()
        self._statement_timeout_seconds = statement_timeout_seconds

    async def execute(
        self,
        request: BoundExecutionRequest,
        cancellation: CancellationToken,
    ) -> tuple[Mapping[str, Any], ...]:
        cancellation.raise_if_cancelled()
        validated = validate_read_query(request.request.statement)
        timeout_ms = int(self._statement_timeout_seconds * 1000)
        connection = await self._factory.connect(
            request.binding.target,
            connect_timeout=self._statement_timeout_seconds,
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ ONLY")
                await cursor.execute(
                    f"SET LOCAL statement_timeout = '{timeout_ms}ms'"
                )
                await cursor.execute(
                    validated.sql,
                    request.request.parameters,
                )
                rows = await cursor.fetchmany(request.request.max_rows + 1)
                cancellation.raise_if_cancelled()
                return tuple(dict(row) for row in rows)
        finally:
            await connection.rollback()
            await connection.close()


class _PsycopgConnectionFactory:
    async def connect(
        self, target: str, *, connect_timeout: float
    ) -> AsyncPostgresConnection:
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required to use AsyncPostgresConnector."
            ) from exc
        return await AsyncConnection.connect(
            target,
            connect_timeout=connect_timeout,
            row_factory=_dict_row_factory(),
        )


def _dict_row_factory() -> object:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required to use AsyncPostgresConnector."
        ) from exc
    return dict_row
