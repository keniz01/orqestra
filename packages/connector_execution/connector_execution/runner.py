"""Reference asynchronous connector runner."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .contracts import (
    BoundExecutionRequest,
    CancellationToken,
    ConnectorCancelledError,
    ConnectorTimeoutError,
    ExecutionRequest,
    ExecutionResult,
    ExecutionTimeout,
)
from .registry import ConnectorBindingRegistry


class AsyncConnector(Protocol):
    async def execute(
        self, request: BoundExecutionRequest, cancellation: CancellationToken
    ) -> Sequence[Mapping[str, Any]]:
        ...


class AsyncConnectorRunner:
    """Bind, run, cancel, timeout, and bound connector results."""

    def __init__(self, bindings: ConnectorBindingRegistry) -> None:
        self._bindings = bindings

    async def run(
        self,
        request: ExecutionRequest,
        connector: AsyncConnector,
        *,
        timeout: ExecutionTimeout,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult:
        token = cancellation or CancellationToken()
        token.raise_if_cancelled()
        binding = self._bindings.resolve(request.principal, request.database_id)
        bound_request = BoundExecutionRequest(request=request, binding=binding)
        work = asyncio.create_task(connector.execute(bound_request, token))
        cancelled = asyncio.create_task(token.wait())
        try:
            done, _ = await asyncio.wait(
                (work, cancelled),
                timeout=timeout.seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                raise ConnectorTimeoutError("Connector execution exceeded its timeout.")
            if cancelled in done:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                raise ConnectorCancelledError("Connector execution was cancelled.")
            return self._bound_result(work.result(), request)
        finally:
            if not cancelled.done():
                cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    @staticmethod
    def _bound_result(
        rows: Sequence[Mapping[str, Any]], request: ExecutionRequest
    ) -> ExecutionResult:
        bounded: list[Mapping[str, Any]] = []
        result_bytes = 0
        truncated = False
        for row_number, row in enumerate(rows):
            if row_number >= request.max_rows:
                truncated = True
                break
            if not isinstance(row, Mapping):
                raise TypeError("Connector rows must be mappings.")
            row_bytes = len(
                json.dumps(dict(row), default=str, separators=(",", ":")).encode("utf-8")
            )
            if result_bytes + row_bytes > request.max_result_bytes:
                truncated = True
                break
            bounded.append(dict(row))
            result_bytes += row_bytes
        return ExecutionResult(tuple(bounded), truncated, result_bytes)
