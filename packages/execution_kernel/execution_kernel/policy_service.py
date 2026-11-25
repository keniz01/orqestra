"""Bounded policy-service contracts and deterministic reference adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .contracts import CapabilityRequest, Principal
from .policy import (
    DecisionProvenance,
    PolicyDecision,
    PolicyEvaluator,
    RulePolicyEvaluator,
)


@dataclass(frozen=True, slots=True)
class PolicyDecisionRequest:
    """The bounded, tenant-scoped input sent to a policy service."""

    user_id: str
    tenant_id: str
    roles: frozenset[str]
    capability: str
    database_id: str
    tables: tuple[str, ...] = ()
    columns: frozenset[str] = frozenset()
    purpose: str = "analytical_read"
    task_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "user_id",
            "tenant_id",
            "capability",
            "database_id",
            "purpose",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        object.__setattr__(self, "roles", _normalized_strings(self.roles, "roles"))
        object.__setattr__(self, "tables", tuple(_normalized_strings(self.tables, "tables")))
        object.__setattr__(
            self, "columns", _normalized_strings(self.columns, "columns")
        )
        if self.task_id is not None and (
            not isinstance(self.task_id, str) or not self.task_id.strip()
        ):
            raise ValueError("task_id must be a non-empty string when provided")

    @classmethod
    def from_capability_request(cls, request: CapabilityRequest) -> PolicyDecisionRequest:
        return cls(
            user_id=request.principal.user_id,
            tenant_id=request.principal.org_id,
            roles=request.principal.roles,
            capability=request.capability,
            database_id=request.database_id,
            tables=request.tables,
            columns=request.columns,
            purpose=request.purpose,
            task_id=request.task_id,
        )


@dataclass(frozen=True, slots=True)
class PolicyDecisionResponse:
    """Typed response required from a policy service."""

    allowed: bool
    reason: str
    provenance: DecisionProvenance
    masked_columns: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise ValueError("allowed must be a boolean")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        object.__setattr__(self, "reason", self.reason.strip())
        object.__setattr__(
            self,
            "masked_columns",
            _normalized_strings(self.masked_columns, "masked_columns"),
        )


class PolicyService(Protocol):
    """Remote or local policy decision point boundary."""

    def decide(self, request: PolicyDecisionRequest) -> object:
        ...


def _normalized_strings(values: object, field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list, set, frozenset)):
        raise ValueError(f"{field_name} must be a collection of strings")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        normalized.add(value.strip().lower())
    return frozenset(normalized)


class PolicyServiceAdapter(PolicyEvaluator):
    """Translate a policy-service boundary into a fail-closed kernel evaluator."""

    def __init__(
        self,
        service: PolicyService,
        *,
        timeout_seconds: float = 1.0,
        source: str = "policy_service",
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not source.strip():
            raise ValueError("source must not be empty")
        self._service = service
        self._timeout_seconds = timeout_seconds
        self._source = source.strip()
        self._clock = clock

    def evaluate(self, request: CapabilityRequest) -> PolicyDecision:
        decision_request = PolicyDecisionRequest.from_capability_request(request)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._service.decide, decision_request)
            raw_response = future.result(timeout=self._timeout_seconds)
        except (FutureTimeoutError, TimeoutError):
            executor.shutdown(wait=False, cancel_futures=True)
            return self._failure(decision_request, "Policy service unavailable: timeout.")
        except (ConnectionError, OSError):
            executor.shutdown(wait=False, cancel_futures=True)
            return self._failure(decision_request, "Policy service unavailable.")
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            return self._failure(decision_request, "Policy service unavailable.")
        else:
            executor.shutdown(wait=True)

        response = self._parse_response(raw_response)
        if response is None:
            return self._failure(decision_request, "Policy service response was malformed.")
        if response.provenance.tenant_id != decision_request.tenant_id:
            return self._failure(decision_request, "Policy service tenant mismatch.")
        return PolicyDecision(
            allowed=response.allowed,
            reason=response.reason,
            masked_columns=response.masked_columns,
            provenance=response.provenance,
        )

    def _parse_response(self, raw_response: object) -> PolicyDecisionResponse | None:
        if isinstance(raw_response, PolicyDecisionResponse):
            return raw_response
        if not isinstance(raw_response, Mapping):
            return None
        try:
            provenance_value = raw_response["provenance"]
            if isinstance(provenance_value, DecisionProvenance):
                provenance = provenance_value
            elif isinstance(provenance_value, Mapping):
                provenance = DecisionProvenance(
                    source=provenance_value["source"],
                    policy_version=provenance_value["policy_version"],
                    decision_id=provenance_value["decision_id"],
                    evaluated_at=provenance_value["evaluated_at"],
                    tenant_id=provenance_value["tenant_id"],
                )
            else:
                return None
            return PolicyDecisionResponse(
                allowed=raw_response["allowed"],
                reason=raw_response["reason"],
                masked_columns=raw_response.get("masked_columns", ()),
                provenance=provenance,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def _failure(self, request: PolicyDecisionRequest, reason: str) -> PolicyDecision:
        decision_id = hashlib.sha256(
            f"{request.tenant_id}:{request.user_id}:{request.capability}:"
            f"{request.database_id}".encode("utf-8")
        ).hexdigest()
        return PolicyDecision(
            allowed=False,
            reason=reason,
            provenance=DecisionProvenance(
                source=self._source,
                policy_version="unavailable",
                decision_id=decision_id,
                evaluated_at=self._clock(),
                tenant_id=request.tenant_id,
            ),
        )


class _ReferencePolicyService:
    def __init__(self, evaluator: RulePolicyEvaluator, policy_version: str) -> None:
        self._evaluator = evaluator
        self._policy_version = policy_version

    def decide(self, request: PolicyDecisionRequest) -> PolicyDecisionResponse:
        capability_request = CapabilityRequest(
            principal=Principal(
                user_id=request.user_id,
                org_id=request.tenant_id,
                roles=request.roles,
            ),
            capability=request.capability,
            database_id=request.database_id,
            tables=request.tables,
            columns=request.columns,
            purpose=request.purpose,
            task_id=request.task_id,
        )
        decision = self._evaluator.evaluate(capability_request)
        decision_id = hashlib.sha256(
            repr(request).encode("utf-8")
        ).hexdigest()
        return PolicyDecisionResponse(
            allowed=decision.allowed,
            reason=decision.reason,
            masked_columns=decision.masked_columns,
            provenance=DecisionProvenance(
                source="reference",
                policy_version=self._policy_version,
                decision_id=decision_id,
                evaluated_at=datetime.now(timezone.utc),
                tenant_id=request.tenant_id,
            ),
        )


class ReferencePolicyServiceAdapter(PolicyServiceAdapter):
    """Deterministic in-memory policy-service adapter for local use and tests."""

    def __init__(
        self,
        *,
        allow_rules: tuple[dict[str, object], ...] = (),
        deny_rules: tuple[dict[str, object], ...] = (),
        policy_version: str = "reference-v1",
    ) -> None:
        super().__init__(
            _ReferencePolicyService(
                RulePolicyEvaluator(allow_rules=allow_rules, deny_rules=deny_rules),
                policy_version,
            ),
            source="reference",
        )
