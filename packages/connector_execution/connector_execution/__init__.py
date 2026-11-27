"""Credential-free asynchronous connector execution contracts."""

from .contracts import (
    BoundExecutionRequest,
    CancellationToken,
    ConnectorBinding,
    ConnectorCancelledError,
    ConnectorIdentity,
    ConnectorTimeoutError,
    ExecutionRequest,
    ExecutionResult,
    ExecutionTimeout,
)
from .registry import ConnectorBindingRegistry, ConnectorResolutionError
from .runner import AsyncConnector, AsyncConnectorRunner
from .integration import GovernedConnectorRunner
from .postgres import AsyncPostgresConnector

__all__ = [
    "AsyncConnector",
    "AsyncConnectorRunner",
    "AsyncPostgresConnector",
    "BoundExecutionRequest",
    "CancellationToken",
    "ConnectorBinding",
    "ConnectorBindingRegistry",
    "ConnectorCancelledError",
    "ConnectorIdentity",
    "ConnectorResolutionError",
    "ConnectorTimeoutError",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionTimeout",
    "GovernedConnectorRunner",
]
