"""Tenant-scoped task state storage with optimistic concurrency."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from uuid import uuid4

from execution_kernel import Principal

from .models import PlanStep, Task, TaskStatus


class TaskNotFound(LookupError):
    """Raised when a task does not exist."""


class TaskScopeError(PermissionError):
    """Raised when a principal accesses another tenant's task."""


class TaskConflict(RuntimeError):
    """Raised when a task version is stale."""


class InvalidTaskTransition(ValueError):
    """Raised when a task state transition is not permitted."""


class InMemoryTaskStore:
    """Reference store for local development and contract tests.

    Production must replace this with a durable store preserving the same
    tenant and optimistic-concurrency invariants.
    """

    _TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
        TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.WAITING_APPROVAL: frozenset(
            {TaskStatus.RUNNING, TaskStatus.CANCELLED}
        ),
        TaskStatus.FAILED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.COMPLETED: frozenset(),
        TaskStatus.CANCELLED: frozenset(),
    }

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create(
        self,
        principal: Principal,
        goal: str,
        steps: Iterable[PlanStep],
    ) -> Task:
        task = Task(
            task_id=str(uuid4()),
            owner=principal,
            goal=goal,
            steps=tuple(steps),
        )
        self._tasks[task.task_id] = task
        return task

    def get(self, principal: Principal, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound("Task was not found.")
        if task.owner.org_id != principal.org_id or task.owner.user_id != principal.user_id:
            raise TaskScopeError("Task is not available to this principal.")
        return task

    def transition(
        self,
        principal: Principal,
        task_id: str,
        target: TaskStatus,
        *,
        expected_version: int,
    ) -> Task:
        current = self.get(principal, task_id)
        if current.version != expected_version:
            raise TaskConflict("Task version is stale.")
        if target not in self._TRANSITIONS[current.status]:
            raise InvalidTaskTransition(
                f"Cannot transition task from {current.status} to {target}."
            )
        updated = current.with_status(target)
        self._tasks[task_id] = updated
        return updated
