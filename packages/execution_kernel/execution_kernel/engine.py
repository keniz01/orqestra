"""The deterministic, transport-independent execution kernel."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .capabilities import CapabilityRegistry, CapabilitySpec
from .contracts import (
    AuditEvent,
    CapabilityRequest,
    CancellationToken,
    DelegationContext,
    ExecutionContext,
    ExecutionCancelled,
    ExecutionTimedOut,
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


class CancellableQueryExecutor(Protocol):
    def execute_with_context(
        self,
        binding: TenantBinding,
        query: ValidatedQuery,
        params: Mapping[str, Any],
        context: ExecutionContext,
    ) -> Sequence[Mapping[str, Any]]:
        ...


class ApprovalChecker(Protocol):
    def is_approved(
        self,
        principal: Principal,
        approval_id: str,
        *,
        task_id: str,
        capability: str,
    ) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    max_rows: int = 5_000
    max_result_bytes: int = 5_000_000
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_rows < 1:
            raise ValueError("max_rows must be positive")
        if self.max_result_bytes < 1:
            raise ValueError("max_result_bytes must be positive")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when provided")


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
        capabilities: CapabilityRegistry | None = None,
        approval_checker: ApprovalChecker | None = None,
        limits: ExecutionLimits | None = None,
    ) -> None:
        self._tenants = tenants
        self._policy = policy
        self._executor = executor
        self._audit_sink = audit_sink
        self._capabilities = capabilities or CapabilityRegistry(
            (
                CapabilitySpec(
                    name=self.READ_CAPABILITY,
                    description="Execute a governed read-only analytical query.",
                    read_only=True,
                ),
            )
        )
        self._approval_checker = approval_checker
        self._limits = limits or ExecutionLimits()

    def execute(
        self,
        *,
        principal: Principal,
        database_id: str,
        plan: QueryPlan,
        task_id: str | None = None,
        delegation: DelegationContext | None = None,
        cancellation: CancellationToken | None = None,
    ) -> QueryResult:
        raw_query_hash = hashlib.sha256(plan.sql.strip().encode("utf-8")).hexdigest()
        capability = self._capabilities.require(self.READ_CAPABILITY)
        if not capability.read_only:
            raise RuntimeError("Read execution capability must be read-only.")
        if (
            delegation is not None
            and task_id is not None
            and task_id != delegation.task_id
        ):
            self._audit_sink(
                AuditEvent(
                    event_type="capability_decision",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=self.READ_CAPABILITY,
                    database_id=database_id,
                    decision="deny",
                    reason="Delegated execution task does not match the requested task.",
                    query_hash=raw_query_hash,
                    task_id=task_id,
                    agent_id=delegation.agent_id,
                )
            )
            raise PermissionError("Delegated execution task does not match the requested task.")
        if delegation is not None and not delegation.allows(
            self.READ_CAPABILITY
        ):
            self._audit_sink(
                AuditEvent(
                    event_type="capability_decision",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=self.READ_CAPABILITY,
                    database_id=database_id,
                    decision="deny",
                    reason="Delegation does not authorize this capability.",
                    query_hash=raw_query_hash,
                    task_id=delegation.task_id,
                    agent_id=delegation.agent_id,
                )
            )
            raise PermissionError("Delegation does not authorize this capability.")
        effective_task_id = delegation.task_id if delegation is not None else task_id
        agent_id = delegation.agent_id if delegation is not None else None
        if capability.requires_approval and (
            delegation is None or delegation.approval_id is None
        ):
            self._audit_sink(
                AuditEvent(
                    event_type="capability_decision",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=self.READ_CAPABILITY,
                    database_id=database_id,
                    decision="deny",
                    reason="Capability approval is required.",
                    query_hash=raw_query_hash,
                    task_id=effective_task_id,
                    agent_id=agent_id,
                )
            )
            raise PermissionError("Capability approval is required.")
        if capability.requires_approval:
            approval_id = delegation.approval_id if delegation is not None else None
            if (
                self._approval_checker is None
                or approval_id is None
                or effective_task_id is None
            ):
                reason = "Capability approval cannot be validated."
                self._audit_sink(
                    AuditEvent(
                        event_type="capability_decision",
                        user_id=principal.user_id,
                        org_id=principal.org_id,
                        capability=self.READ_CAPABILITY,
                        database_id=database_id,
                        decision="deny",
                        reason=reason,
                        query_hash=raw_query_hash,
                        task_id=effective_task_id,
                        agent_id=agent_id,
                    )
                )
                raise PermissionError(reason)
            try:
                approved = self._approval_checker.is_approved(
                    principal,
                    approval_id,
                    task_id=effective_task_id,
                    capability=self.READ_CAPABILITY,
                )
            except (LookupError, PermissionError):
                approved = False
            if not approved:
                reason = "Capability approval is invalid, expired, or out of scope."
                self._audit_sink(
                    AuditEvent(
                        event_type="capability_decision",
                        user_id=principal.user_id,
                        org_id=principal.org_id,
                        capability=self.READ_CAPABILITY,
                        database_id=database_id,
                        decision="deny",
                        reason=reason,
                        query_hash=raw_query_hash,
                        task_id=effective_task_id,
                        agent_id=agent_id,
                    )
                )
                raise PermissionError(reason)
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
                    task_id=effective_task_id,
                    agent_id=agent_id,
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
                    task_id=effective_task_id,
                    agent_id=agent_id,
                )
            )
            raise

        request = CapabilityRequest(
            principal=principal,
            capability=self.READ_CAPABILITY,
            database_id=database_id,
            tables=validated.tables,
            columns=validated.columns,
            task_id=effective_task_id,
            delegation=delegation,
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
                task_id=effective_task_id,
                agent_id=agent_id,
            )
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        context = ExecutionContext(
            cancellation=cancellation or CancellationToken(),
            timeout_seconds=self._limits.timeout_seconds,
        )
        try:
            context.ensure_active()
            execute_with_context = getattr(self._executor, "execute_with_context", None)
            if execute_with_context is not None:
                raw_rows = execute_with_context(
                    binding,
                    validated,
                    plan.params,
                    context,
                )
            else:
                raw_rows = self._executor.execute(binding, validated, plan.params)
            context.ensure_active()
        except (ExecutionCancelled, ExecutionTimedOut) as exc:
            self._audit_sink(
                AuditEvent(
                    event_type="capability_execution",
                    user_id=principal.user_id,
                    org_id=principal.org_id,
                    capability=request.capability,
                    database_id=database_id,
                    decision="deny",
                    reason=str(exc),
                    query_hash=query_hash,
                    task_id=effective_task_id,
                    agent_id=agent_id,
                )
            )
            raise
        max_rows = min(
            self._limits.max_rows,
            capability.max_rows if capability.max_rows is not None else self._limits.max_rows,
        )
        max_result_bytes = min(
            self._limits.max_result_bytes,
            (
                capability.max_result_bytes
                if capability.max_result_bytes is not None
                else self._limits.max_result_bytes
            ),
        )
        masked_rows_list: list[Mapping[str, Any]] = []
        result_bytes = 0
        truncated = False
        for row_number, row in enumerate(raw_rows):
            if row_number >= max_rows:
                truncated = True
                break
            masked_row = {
                key: None if str(key).lower() in decision.masked_columns else value
                for key, value in row.items()
            }
            row_bytes = len(
                json.dumps(
                    masked_row,
                    default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if result_bytes + row_bytes > max_result_bytes:
                truncated = True
                break
            masked_rows_list.append(masked_row)
            result_bytes += row_bytes
        masked_rows = tuple(masked_rows_list)
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
                task_id=effective_task_id,
                agent_id=agent_id,
            )
        )
        return QueryResult(
            rows=masked_rows,
            truncated=truncated,
            result_bytes=result_bytes,
        )
