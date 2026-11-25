"""Registry for typed, governable capability definitions."""

from __future__ import annotations

from dataclasses import dataclass


class CapabilityError(PermissionError):
    """Raised when a capability is unknown or incorrectly registered."""


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Static contract describing an executable capability."""

    name: str
    description: str
    read_only: bool
    requires_approval: bool = False
    max_rows: int | None = None
    max_result_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("capability name must not be empty")
        if not self.description.strip():
            raise ValueError("capability description must not be empty")
        for field_name in ("max_rows", "max_result_bytes"):
            value = getattr(self, field_name)
            if value is not None and value < 1:
                raise ValueError(f"{field_name} must be positive when provided")


class CapabilityRegistry:
    """Immutable-by-contract registry with explicit duplicate protection."""

    def __init__(self, capabilities: tuple[CapabilitySpec, ...] = ()) -> None:
        self._capabilities: dict[str, CapabilitySpec] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: CapabilitySpec) -> None:
        if capability.name in self._capabilities:
            raise CapabilityError(f"Capability is already registered: {capability.name}")
        self._capabilities[capability.name] = capability

    def require(self, name: str) -> CapabilitySpec:
        capability = self._capabilities.get(name)
        if capability is None:
            raise CapabilityError(f"Capability is not registered: {name}")
        return capability

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))
