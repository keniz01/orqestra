"""Server-owned tenant/database binding resolution."""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import Principal, TenantBinding


class TenantResolutionError(PermissionError):
    """Raised when a principal cannot resolve the requested logical database."""


class TenantBindingRegistry:
    """Resolve logical database IDs without accepting connection details from callers."""

    def __init__(self, bindings: Mapping[tuple[str, str], TenantBinding]) -> None:
        self._bindings = dict(bindings)

    def resolve(self, principal: Principal, database_id: str) -> TenantBinding:
        key = (principal.org_id, database_id)
        binding = self._bindings.get(key)
        if binding is None:
            raise TenantResolutionError("Database is not available to this tenant.")
        return binding
