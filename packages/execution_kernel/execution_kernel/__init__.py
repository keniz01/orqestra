"""Transport-independent governed data execution primitives."""

from .contracts import (
    AuditEvent,
    CapabilityRequest,
    Principal,
    QueryPlan,
    QueryResult,
    TenantBinding,
)
from .engine import ExecutionKernel, ExecutionLimits
from .policy import PolicyDecision, PolicyEvaluator, RulePolicyEvaluator
from .sql import SqlValidationError, validate_read_query
from .tenant import TenantBindingRegistry, TenantResolutionError

__all__ = [
    "AuditEvent",
    "CapabilityRequest",
    "ExecutionKernel",
    "ExecutionLimits",
    "PolicyDecision",
    "PolicyEvaluator",
    "Principal",
    "QueryPlan",
    "QueryResult",
    "RulePolicyEvaluator",
    "SqlValidationError",
    "TenantBinding",
    "TenantBindingRegistry",
    "TenantResolutionError",
    "validate_read_query",
]
