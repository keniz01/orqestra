from __future__ import annotations

import pytest

from execution_kernel import Principal
from task_runtime import (
    InMemoryTaskStore,
    InvalidTaskTransition,
    PlanStep,
    TaskConflict,
    TaskScopeError,
    TaskStatus,
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
