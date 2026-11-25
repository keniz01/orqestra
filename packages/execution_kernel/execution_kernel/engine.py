"""The deterministic, transport-independent execution kernel."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import (
    AuditEvent,
    CapabilityRequest,
    Principal,
    QueryPlan,
    QueryResult,
    TenantBinding,
)
from .policy import PolicyEvaluator
from .sql import SqlValidationError, ValidatedQuery, validate_read_query
from .tenant import TenantBindingRegistry, TenantResolutionError


class QueryExecutor(Protocol):
    def execute(
        self, binding: TenantBinding, query: ValidatedQuery, params: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    max_rows: int = 5_000

    def __post_init__(self) -> None:
        if self.max_rows < 1:
            raise ValueError("max_rows must be positive")


class ExecutionKernel:
    """Authenticate-by-contract, authorize, validate, execute, and audit reads."""

    READ_CAPABILITY = "data.execute_read_query"

    def __init__(
        self,
        *,
        tenants: TenantBindingRegistry,
        policy: PolicyEvaluator,
        executor: QueryExecutor,
        audit_sink: Callable[[AuditEvent], None],
        limits: ExecutionLimits | None = None,
    ) -> None:
        self._tenants = tenants
        self._policy = policy
        self._executor = executor
        self._audit_sink = audit_sink
        self._limits = limits or ExecutionLimits()

    def execute(
        self,
        *,
        principal: Principal,
        database_id: str,
        plan: QueryPlan,
        task_id: str | None = None,
    ) -> QueryResult:
        raw_query_hash = hashlib.sha256(plan.sql.strip().encode("utf-8")).hexdigest()
        try:
            binding = self._tenants.resolve(principal, database_id)
        except TenantResolutionError as exc:
            self._audit_sink(
                AuditEvent(
                    event_type="capability_decision",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=self.READ_CAPABILITY,
                    database_id=database_id,
                    decision="deny",
                    reason=str(exc),
                    query_hash=raw_query_hash,
                    task_id=task_id,
                )
            )
            raise

        try:
            validated = validate_read_query(plan.sql)
        except SqlValidationError as exc:
            self._audit_sink(
                AuditEvent(
                    event_type="capability_decision",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=self.READ_CAPABILITY,
                    database_id=database_id,
                    decision="deny",
                    reason=str(exc),
                    query_hash=raw_query_hash,
                    task_id=task_id,
                )
            )
            raise

        request = CapabilityRequest(
            principal=principal,
            capability=self.READ_CAPABILITY,
            database_id=database_id,
            tables=validated.tables,
            columns=validated.columns,
            task_id=task_id,
        )
        decision = self._policy.evaluate(request)
        query_hash = hashlib.sha256(validated.sql.encode("utf-8")).hexdigest()

        self._audit_sink(
            AuditEvent(
                event_type="capability_decision",
                user_id=principal.user_id,
                org_id=principal.org_id,
                capability=request.capability,
                database_id=database_id,
                decision="allow" if decision.allowed else "deny",
                reason=decision.reason,
                query_hash=query_hash,
                task_id=task_id,
            )
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        raw_rows = self._executor.execute(binding, validated, plan.params)
        bounded_rows = tuple(raw_rows[: self._limits.max_rows])
        truncated = len(raw_rows) > self._limits.max_rows
        masked_rows = tuple(
            {
                key: None if str(key).lower() in decision.masked_columns else value
                for key, value in row.items()
            }
            for row in bounded_rows
        )
        self._audit_sink(
            AuditEvent(
                event_type="capability_executed",
                user_id=principal.user_id,
                org_id=principal.org_id,
                capability=request.capability,
                database_id=database_id,
                decision="allow",
                reason="Read query executed.",
                query_hash=query_hash,
                task_id=task_id,
            )
        )
        return QueryResult(rows=masked_rows, truncated=truncated)
