"""Governed boundary between policy decisions and connector execution."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from execution_kernel import (
    AuditEvent,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilitySpec,
    PolicyDecision,
    PolicyEvaluator,
)

from .contracts import (
    CancellationToken,
    ConnectorCancelledError,
    ConnectorTimeoutError,
    ExecutionRequest,
    ExecutionResult,
    ExecutionTimeout,
)
from .runner import AsyncConnector, AsyncConnectorRunner
from .registry import ConnectorBindingRegistry, ConnectorResolutionError


class GovernedConnectorRunner:
    """Authorize a logical request before running a server-bound connector."""

    CONNECTOR_CAPABILITY = "data.execute_read_query"

    def __init__(
        self,
        *,
        policy: PolicyEvaluator,
        bindings: ConnectorBindingRegistry,
        audit_sink: Callable[[AuditEvent], None],
        capabilities: CapabilityRegistry | None = None,
        runner: AsyncConnectorRunner | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._policy = policy
        self._bindings = bindings
        self._audit_sink = audit_sink
        self._runner = runner or AsyncConnectorRunner(bindings)
        self._clock = clock
        self._capabilities = capabilities or CapabilityRegistry(
            (
                CapabilitySpec(
                    name=self.CONNECTOR_CAPABILITY,
                    description="Execute a governed connector operation.",
                    read_only=True,
                ),
            )
        )

    async def run(
        self,
        request: ExecutionRequest,
        connector: AsyncConnector,
        *,
        timeout: ExecutionTimeout,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult:
        capability = self._capabilities.require(self.CONNECTOR_CAPABILITY)
        token = cancellation or CancellationToken()
        query_hash = hashlib.sha256(request.statement.encode("utf-8")).hexdigest()

        try:
            token.raise_if_cancelled()
            binding = self._bindings.resolve(request.principal, request.database_id)
        except ConnectorCancelledError as exc:
            self._emit(request, "deny", str(exc), query_hash=query_hash)
            raise
        except ConnectorResolutionError as exc:
            self._emit(request, "deny", str(exc), query_hash=query_hash)
            raise

        effective_request = replace(
            request,
            max_rows=min(
                request.max_rows,
                capability.max_rows if capability.max_rows is not None else request.max_rows,
            ),
            max_result_bytes=min(
                request.max_result_bytes,
                (
                    capability.max_result_bytes
                    if capability.max_result_bytes is not None
                    else request.max_result_bytes
                ),
            ),
        )
        policy_request = CapabilityRequest(
            principal=request.principal,
            capability=self.CONNECTOR_CAPABILITY,
            database_id=request.database_id,
            purpose="connector_execution",
            task_id=request.task_id,
        )
        try:
            decision = self._policy.evaluate(policy_request)
        except Exception:
            self._emit(
                request,
                "deny",
                "Policy service unavailable.",
                query_hash=query_hash,
            )
            raise PermissionError("Policy service unavailable.")
        if not isinstance(decision, PolicyDecision):
            self._emit(
                request,
                "deny",
                "Policy service response was malformed.",
                query_hash=query_hash,
            )
            raise PermissionError("Policy service response was malformed.")
        if decision.provenance is not None and (
            decision.provenance.tenant_id != request.principal.org_id
        ):
            reason = "Policy service tenant mismatch."
            self._emit(request, "deny", reason, query_hash=query_hash)
            raise PermissionError(reason)
        self._emit(
            request,
            "allow" if decision.allowed else "deny",
            decision.reason,
            query_hash=query_hash,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        try:
            result = await self._runner.run(
                effective_request,
                connector,
                timeout=timeout,
                cancellation=token,
            )
        except (ConnectorCancelledError, ConnectorTimeoutError) as exc:
            self._emit(request, "deny", str(exc), query_hash=query_hash)
            raise
        except Exception:
            self._emit(
                request,
                "deny",
                "Connector execution failed.",
                query_hash=query_hash,
            )
            raise
        self._emit(
            request,
            "allow",
            "Connector execution completed.",
            query_hash=query_hash,
            event_type="capability_executed",
            payload={
                "connector_id": binding.identity.connector_id,
                "rows": len(result.rows),
                "result_bytes": result.result_bytes,
                "truncated": result.truncated,
            },
        )
        return result

    def _emit(
        self,
        request: ExecutionRequest,
        decision: str,
        reason: str,
        *,
        query_hash: str,
        event_type: str = "capability_decision",
        payload: dict[str, object] | None = None,
    ) -> None:
        self._audit_sink(
            AuditEvent(
                event_type=event_type,
                user_id=request.principal.user_id,
                org_id=request.principal.org_id,
                capability=self.CONNECTOR_CAPABILITY,
                database_id=request.database_id,
                decision=decision,
                reason=reason,
                query_hash=query_hash,
                task_id=request.task_id,
                payload=payload or {},
                occurred_at=self._clock(),
            )
        )
