"""Typed, credential-free contracts for asynchronous connector execution."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from execution_kernel import Principal


_CREDENTIAL_KEY = re.compile(
    r"(?:credential|password|passwd|secret|token|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _reject_credentials(value: Any, path: str = "parameters") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _CREDENTIAL_KEY.search(str(key)):
                raise ValueError(f"{path} contains credential-bearing field")
            _reject_credentials(nested, f"{path}.{key}")
    elif isinstance(value, (tuple, list, set, frozenset)):
        for index, nested in enumerate(value):
            _reject_credentials(nested, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class ConnectorIdentity:
    """A server-owned connector identity; callers provide only a logical database."""

    org_id: str
    database_id: str
    connector_id: str

    def __post_init__(self) -> None:
        for name in ("org_id", "database_id", "connector_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ConnectorBinding:
    """Server-owned routing data used internally by a connector adapter."""

    identity: ConnectorIdentity
    target: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _text(self.target, "target"))


@dataclass(frozen=True, slots=True)
class ExecutionTimeout:
    """The maximum duration a connector invocation may run."""

    seconds: float

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("seconds must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """A logical request with no connector routing or credential inputs."""

    principal: Principal
    database_id: str
    statement: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    max_rows: int = 5_000
    max_result_bytes: int = 5_000_000
    requested_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_id", _text(self.database_id, "database_id"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        if self.max_rows < 1 or self.max_result_bytes < 1:
            raise ValueError("result bounds must be positive")
        _reject_credentials(self.parameters)
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True)
class BoundExecutionRequest:
    """Internal request after server-side tenant/database binding resolution."""

    request: ExecutionRequest
    binding: ConnectorBinding


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """A bounded connector result."""

    rows: tuple[Mapping[str, Any], ...]
    truncated: bool = False
    result_bytes: int = 0


class CancellationToken:
    """Thread-safe cooperative cancellation signal for connector work."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ConnectorCancelledError("Connector execution was cancelled.")

    async def wait(self) -> None:
        await self._event.wait()


class ConnectorCancelledError(asyncio.CancelledError):
    """Raised when a connector invocation is cancelled by its caller."""


class ConnectorTimeoutError(TimeoutError):
    """Raised when a connector invocation exceeds its execution timeout."""
