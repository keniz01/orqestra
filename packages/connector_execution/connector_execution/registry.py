"""Server-owned connector binding resolution."""

from __future__ import annotations

from collections.abc import Mapping

from execution_kernel import Principal

from .contracts import ConnectorBinding


class ConnectorResolutionError(PermissionError):
    """Raised when a principal cannot access a logical database."""


class ConnectorBindingRegistry:
    """Resolve connector bindings without accepting routing or credentials from callers."""

    def __init__(self, bindings: Mapping[tuple[str, str], ConnectorBinding]) -> None:
        self._bindings = dict(bindings)

    def resolve(self, principal: Principal, database_id: str) -> ConnectorBinding:
        binding = self._bindings.get((principal.org_id, database_id))
        if binding is None:
            raise ConnectorResolutionError("Database is not available to this tenant.")
        if binding.identity.org_id != principal.org_id or binding.identity.database_id != database_id:
            raise ConnectorResolutionError("Connector binding is inconsistent.")
        return binding
