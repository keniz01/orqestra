"""Transport-independent governance event bus."""

from __future__ import annotations

from collections.abc import Callable

from .ledger import GovernanceLedger
from .models import GovernanceEvent


class GovernanceEventBus:
    """Persist each event before delivering it to subscribed handlers."""

    def __init__(self, ledger: GovernanceLedger) -> None:
        self._ledger = ledger
        self._handlers: dict[str, list[Callable[[GovernanceEvent], None]]] = {}

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[GovernanceEvent], None],
    ) -> None:
        if not event_type.strip():
            raise ValueError("event_type must not be empty")
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: GovernanceEvent) -> None:
        self._ledger.append(event)
        for handler in self._handlers.get(event.event_type, ()):
            handler(event)
