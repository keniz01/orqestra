from __future__ import annotations

import pytest

from execution_kernel import Principal
from task_runtime import (
    InMemoryTaskStore,
    InMemoryTaskRepository,
    InvalidTaskTransition,
    PlanStep,
    TaskConflict,
    TaskRepository,
    TaskScopeError,
    TaskStatus,
    SQLiteTaskRepository,
)


def principal(user_id: str = "user-1", org_id: str = "org-1") -> Principal:
    return Principal(user_id=user_id, org_id=org_id, roles=frozenset({"viewer"}))


def create_task(store: InMemoryTaskStore):
    return store.create(
        principal(),
        "Investigate customer retention",
        [PlanStep("step-1", "data.execute_read_query")],
    )


def test_task_transitions_are_versioned_and_tenant_scoped():
    store = InMemoryTaskStore()
    task = create_task(store)

    running = store.transition(
        principal(),
        task.task_id,
        TaskStatus.RUNNING,
        expected_version=task.version,
    )
    completed = store.transition(
        principal(),
        task.task_id,
        TaskStatus.COMPLETED,
        expected_version=running.version,
    )

    assert completed.status is TaskStatus.COMPLETED
    assert completed.version == 2

    with pytest.raises(TaskScopeError):
        store.get(principal(user_id="other-user"), task.task_id)


def test_stale_and_invalid_transitions_are_rejected():
    store = InMemoryTaskStore()
    task = create_task(store)

    store.transition(
        principal(),
        task.task_id,
        TaskStatus.RUNNING,
        expected_version=task.version,
    )

    with pytest.raises(TaskConflict):
        store.transition(
            principal(),
            task.task_id,
            TaskStatus.CANCELLED,
            expected_version=task.version,
        )

    with pytest.raises(InvalidTaskTransition):
        store.transition(
            principal(),
            task.task_id,
            TaskStatus.PENDING,
            expected_version=1,
        )


def test_task_store_emits_governance_events_for_state_changes():
    events = []
    store = InMemoryTaskStore(event_sink=events.append)

    task = create_task(store)
    store.transition(
        principal(),
        task.task_id,
        TaskStatus.RUNNING,
        expected_version=task.version,
    )

    assert [event.event_type for event in events] == [
        "task.created",
        "task.transitioned",
    ]
    assert all(event.org_id == "org-1" for event in events)


def test_in_memory_task_adapter_satisfies_repository_contract():
    store = InMemoryTaskRepository()

    assert isinstance(store, TaskRepository)
    assert isinstance(store, InMemoryTaskStore)


def test_sqlite_task_repository_preserves_state_and_scope_after_reopen(tmp_path):
    database = tmp_path / "tasks.sqlite"
    first_store = SQLiteTaskRepository(str(database))
    task = first_store.create(
        principal(),
        "Investigate customer retention",
        [PlanStep("step-1", "data.execute_read_query")],
    )
    running = first_store.transition(
        principal(),
        task.task_id,
        TaskStatus.RUNNING,
        expected_version=task.version,
    )
    first_store.close()

    second_store = SQLiteTaskRepository(str(database))
    restored = second_store.get(principal(), task.task_id)
    assert restored.status is TaskStatus.RUNNING
    assert restored.version == running.version
    with pytest.raises(TaskScopeError):
        second_store.get(principal(user_id="other-user"), task.task_id)
    second_store.close()
