from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from workflow_reliability import (
    CheckpointConflict,
    IdempotencyConflict,
    InMemoryCancellationStore,
    InMemoryCheckpointStore,
    InMemoryIdempotencyStore,
    InMemoryLeaseStore,
    LeaseConflict,
    LeaseOwnershipError,
    RetryPolicy,
    SQLiteReliabilityStore,
    WorkflowCancelled,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_lease_expiry_allows_reacquisition():
    store = InMemoryLeaseStore()
    first = store.acquire("workflow-1", "worker-1", timedelta(seconds=10), now=NOW)

    assert store.get("workflow-1", now=NOW + timedelta(seconds=9)) == first
    with pytest.raises(LeaseConflict):
        store.acquire("workflow-1", "worker-2", timedelta(seconds=10), now=NOW)

    replacement = store.acquire(
        "workflow-1", "worker-2", timedelta(seconds=10), now=NOW + timedelta(seconds=10)
    )
    assert replacement.owner_id == "worker-2"
    assert replacement.lease_id != first.lease_id


def test_lease_rejects_stale_ownership():
    store = InMemoryLeaseStore()
    lease = store.acquire("workflow-1", "worker-1", timedelta(minutes=1), now=NOW)

    with pytest.raises(LeaseOwnershipError):
        store.renew(
            "workflow-1",
            lease.lease_id,
            "worker-2",
            timedelta(minutes=1),
            now=NOW,
        )


def test_retry_policy_is_bounded_by_attempts_and_delay():
    policy = RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=1,
        backoff_multiplier=2,
        max_delay_seconds=2,
    )

    assert [policy.can_retry(attempt) for attempt in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    assert [policy.delay_for(attempt) for attempt in range(4)] == [1, 2, 2, 2]


def test_idempotency_returns_duplicate_result_without_running_operation():
    store = InMemoryIdempotencyStore()
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        return "completed"

    assert store.execute("request-1", "hash-1", operation) == "completed"
    assert store.execute("request-1", "hash-1", operation) == "completed"
    assert calls == 1

    with pytest.raises(IdempotencyConflict):
        store.execute("request-1", "different-hash", operation)


def test_cancellation_is_idempotent_and_observable():
    store = InMemoryCancellationStore()
    cancellation = store.request("workflow-1", now=NOW)

    assert store.request("workflow-1", reason="ignored", now=NOW) == cancellation
    with pytest.raises(WorkflowCancelled):
        store.raise_if_cancelled("workflow-1")


def test_checkpoint_versions_require_current_version():
    store = InMemoryCheckpointStore()
    first = store.save("workflow-1", {"step": 1}, now=NOW)
    second = store.save(
        "workflow-1",
        {"step": 2},
        expected_version=first.version,
        now=NOW + timedelta(seconds=1),
    )

    assert second.version == 2
    assert store.get("workflow-1", version=2).state == {"step": 2}
    with pytest.raises(CheckpointConflict):
        store.save("workflow-1", {"step": 3}, expected_version=first.version)


def test_sqlite_reliability_state_survives_reopen(tmp_path):
    database = tmp_path / "workflow-state.sqlite"
    first_store = SQLiteReliabilityStore(str(database))
    lease = first_store.acquire_lease(
        "workflow-1",
        "worker-1",
        timedelta(minutes=1),
        now=NOW,
    )
    first_store.request_cancellation("workflow-2", now=NOW)
    checkpoint = first_store.save_checkpoint(
        "workflow-1",
        {"completed_steps": ["step-1"]},
        now=NOW,
    )
    assert first_store.execute_idempotent("request-1", "hash-1", lambda: {"ok": True}) == {
        "ok": True
    }
    first_store.close()

    second_store = SQLiteReliabilityStore(str(database))
    assert second_store.get_lease("workflow-1", now=NOW) == lease
    assert second_store.get_cancellation("workflow-2") is not None
    assert second_store.get_checkpoint("workflow-1").state == {
        "completed_steps": ["step-1"]
    }
    assert second_store.execute_idempotent("request-1", "hash-1", lambda: {"ok": False}) == {
        "ok": True
    }
    second_store.close()
