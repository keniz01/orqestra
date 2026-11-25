"""Governance ledger contracts and an in-memory reference implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from execution_kernel import Principal

from .models import GovernanceEvent


class LedgerConflict(RuntimeError):
    """Raised when an event ID is reused with different event data."""


@runtime_checkable
class GovernanceLedger(Protocol):
    """Persistence boundary for append-only governance events."""

    def append(self, event: GovernanceEvent) -> None:
        ...

    def events_for(
        self,
        principal: Principal,
        *,
        task_id: str | None = None,
    ) -> tuple[GovernanceEvent, ...]:
        ...


GovernanceRepository = GovernanceLedger


class InMemoryGovernanceLedger:
    """Reference ledger with idempotent append and tenant-scoped reads."""

    def __init__(self) -> None:
        self._events: dict[str, GovernanceEvent] = {}
        self._order: list[str] = []

    def append(self, event: GovernanceEvent) -> None:
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing != event:
                raise LedgerConflict("Event ID is already bound to different data.")
            return
        self._events[event.event_id] = event
        self._order.append(event.event_id)

    def events_for(
        self,
        principal: Principal,
        *,
        task_id: str | None = None,
    ) -> tuple[GovernanceEvent, ...]:
        if task_id is not None and not task_id.strip():
            raise ValueError("task_id must not be empty when provided")
        return tuple(
            event
            for event_id in self._order
            if (event := self._events[event_id]).org_id == principal.org_id
            and (task_id is None or event.task_id == task_id)
        )


InMemoryGovernanceRepository = InMemoryGovernanceLedger
