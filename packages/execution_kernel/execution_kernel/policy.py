"""Fail-closed capability authorization for the execution kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import CapabilityRequest, Principal


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    masked_columns: frozenset[str] = frozenset()


class PolicyEvaluator(Protocol):
    """Policy decision point used by the kernel."""

    def evaluate(self, request: CapabilityRequest) -> PolicyDecision:
        ...


@dataclass(frozen=True, slots=True)
class _Rule:
    capability: str
    org_id: str | None
    roles: frozenset[str]
    database_id: str | None
    tables: frozenset[str]
    masked_columns: frozenset[str]

    def matches(self, request: CapabilityRequest) -> bool:
        return (
            self.capability == request.capability
            and (self.org_id is None or self.org_id == request.principal.org_id)
            and (self.database_id is None or self.database_id == request.database_id)
            and (not self.roles or bool(self.roles & request.principal.roles))
            and (not self.tables or set(request.tables).issubset(self.tables))
        )


class RulePolicyEvaluator:
    """Small deterministic policy evaluator with deny-by-default semantics.

    This is a kernel test/development implementation. Production policy
    decisions should be supplied by the platform policy service/OPA adapter.
    """

    def __init__(
        self,
        *,
        allow_rules: tuple[dict[str, object], ...] = (),
        deny_rules: tuple[dict[str, object], ...] = (),
    ) -> None:
        self._allow_rules = tuple(self._parse_rule(rule) for rule in allow_rules)
        self._deny_rules = tuple(self._parse_rule(rule) for rule in deny_rules)

    @staticmethod
    def _parse_rule(raw: dict[str, object]) -> _Rule:
        return _Rule(
            capability=str(raw["capability"]),
            org_id=str(raw["org_id"]) if raw.get("org_id") is not None else None,
            roles=frozenset(str(role).lower() for role in raw.get("roles", ())),
            database_id=(
                str(raw["database_id"]) if raw.get("database_id") is not None else None
            ),
            tables=frozenset(str(table).lower() for table in raw.get("tables", ())),
            masked_columns=frozenset(
                str(column).lower() for column in raw.get("masked_columns", ())
            ),
        )

    def evaluate(self, request: CapabilityRequest) -> PolicyDecision:
        matching_denies = [rule for rule in self._deny_rules if rule.matches(request)]
        if matching_denies:
            return PolicyDecision(False, "Denied by policy.")

        matching_allows = [rule for rule in self._allow_rules if rule.matches(request)]
        if not matching_allows:
            return PolicyDecision(False, "No allow policy matched the capability.")

        masked_columns = frozenset().union(
            *(rule.masked_columns for rule in matching_allows)
        )
        return PolicyDecision(True, "Allowed by policy.", masked_columns)


def principal_has_any_role(principal: Principal, roles: frozenset[str]) -> bool:
    """Return whether a normalized principal has at least one requested role."""

    return bool(principal.roles & roles)
