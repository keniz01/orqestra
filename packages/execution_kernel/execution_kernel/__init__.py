"""Transport-independent governed data execution primitives."""

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
from .capabilities import CapabilityError, CapabilityRegistry, CapabilitySpec
from .engine import (
    ApprovalChecker,
    CancellableQueryExecutor,
    ExecutionKernel,
    ExecutionLimits,
    QueryExecutor,
)
from .policy import PolicyDecision, PolicyEvaluator, RulePolicyEvaluator
from .sql import SqlValidationError, validate_read_query
from .tenant import TenantBindingRegistry, TenantResolutionError

__all__ = [
    "AuditEvent",
    "ApprovalChecker",
    "CapabilityRequest",
    "CapabilityError",
    "CapabilityRegistry",
    "CapabilitySpec",
    "CancellationToken",
    "CancellableQueryExecutor",
    "DelegationContext",
    "ExecutionContext",
    "ExecutionCancelled",
    "ExecutionKernel",
    "ExecutionLimits",
    "PolicyDecision",
    "PolicyEvaluator",
    "Principal",
    "QueryPlan",
    "QueryResult",
    "QueryExecutor",
    "RulePolicyEvaluator",
    "SqlValidationError",
    "TenantBinding",
    "TenantBindingRegistry",
    "TenantResolutionError",
    "ExecutionTimedOut",
    "validate_read_query",
]
