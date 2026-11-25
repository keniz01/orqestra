from __future__ import annotations

import pytest
from datetime import datetime

from execution_kernel import Principal
from governance import (
    GovernanceEvent,
    GovernanceEventBus,
    GovernanceRepository,
    InMemoryGovernanceLedger,
    InMemoryGovernanceRepository,
    LedgerConflict,
    SQLiteGovernanceLedger,
)


def principal(org_id: str = "org-1") -> Principal:
    return Principal(user_id="user-1", org_id=org_id)


def event(event_id: str = "event-1", org_id: str = "org-1") -> GovernanceEvent:
    return GovernanceEvent(
        event_id=event_id,
        org_id=org_id,
        event_type="task.created",
        actor_user_id="user-1",
        decision="allow",
        reason="Task created.",
        task_id="task-1",
    )


def test_ledger_is_idempotent_and_filters_events_by_tenant_and_task():
    ledger = InMemoryGovernanceLedger()
    first = event()
    ledger.append(first)
    ledger.append(first)
    ledger.append(event(event_id="event-2", org_id="org-2"))

    assert ledger.events_for(principal()) == (first,)
    assert ledger.events_for(principal(), task_id="task-1") == (first,)
    assert ledger.events_for(principal(), task_id="other-task") == ()


def test_ledger_rejects_event_id_reuse_with_different_data():
    ledger = InMemoryGovernanceLedger()
    ledger.append(event())

    with pytest.raises(LedgerConflict):
        ledger.append(
            GovernanceEvent(
                event_id="event-1",
                org_id="org-1",
                event_type="task.failed",
                actor_user_id="user-1",
                decision="deny",
                reason="Task failed.",
                task_id="task-1",
            )
        )


def test_event_payload_is_copied_and_timestamps_require_timezone():
    payload = {"version": 1}
    governance_event = GovernanceEvent(
        org_id="org-1",
        event_type="task.created",
        actor_user_id="user-1",
        decision="allow",
        reason="Task created.",
        payload=payload,
    )
    payload["version"] = 2

    assert governance_event.payload == {"version": 1}

    with pytest.raises(ValueError, match="timezone"):
        GovernanceEvent(
            org_id="org-1",
            event_type="task.created",
            actor_user_id="user-1",
            decision="allow",
            reason="Task created.",
            occurred_at=datetime(2026, 1, 1),
        )


def test_in_memory_governance_adapter_satisfies_repository_contract():
    ledger = InMemoryGovernanceRepository()

    assert isinstance(ledger, GovernanceRepository)
    assert isinstance(ledger, InMemoryGovernanceLedger)


def test_sqlite_governance_ledger_is_idempotent_and_tenant_scoped(tmp_path):
    database = tmp_path / "governance.sqlite"
    first_ledger = SQLiteGovernanceLedger(str(database))
    first = event()
    first_ledger.append(first)
    first_ledger.append(first)
    first_ledger.close()

    second_ledger = SQLiteGovernanceLedger(str(database))
    assert second_ledger.events_for(principal()) == (first,)
    assert second_ledger.events_for(Principal(user_id="other", org_id="org-2")) == ()
    second_ledger.close()


def test_event_bus_persists_before_delivering_to_subscribers():
    ledger = InMemoryGovernanceLedger()
    received = []
    bus = GovernanceEventBus(ledger)
    bus.subscribe("task.created", received.append)
    current = event()

    bus.publish(current)

    assert received == [current]
    assert ledger.events_for(principal()) == (current,)
