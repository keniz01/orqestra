"""SQLite-backed task repository preserving task ownership and version rules."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from execution_kernel import Principal
from governance import GovernanceEvent

from .models import PlanStep, StepStatus, Task, TaskStatus
from .store import (
    InvalidTaskTransition,
    TaskConflict,
    TaskNotFound,
    TaskScopeError,
)


def _connection(database: str | sqlite3.Connection) -> sqlite3.Connection:
    connection = database if isinstance(database, sqlite3.Connection) else sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _principal_json(principal: Principal) -> str:
    return json.dumps(
        {
            "user_id": principal.user_id,
            "org_id": principal.org_id,
            "roles": sorted(principal.roles),
            "attributes": dict(principal.attributes),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _steps_json(steps: tuple[PlanStep, ...]) -> str:
    return json.dumps(
        [
            {
                "step_id": step.step_id,
                "capability": step.capability,
                "input": dict(step.input),
                "status": step.status.value,
            }
            for step in steps
        ],
        separators=(",", ":"),
        sort_keys=True,
    )


def _task_from_row(row: sqlite3.Row) -> Task:
    principal = json.loads(row["owner_json"])
    return Task(
        task_id=row["task_id"],
        owner=Principal(
            user_id=principal["user_id"],
            org_id=principal["org_id"],
            roles=frozenset(principal["roles"]),
            attributes=principal["attributes"],
        ),
        goal=row["goal"],
        steps=tuple(
            PlanStep(
                step_id=step["step_id"],
                capability=step["capability"],
                input=step["input"],
                status=StepStatus(step["status"]),
            )
            for step in json.loads(row["steps_json"])
        ),
        status=TaskStatus(row["status"]),
        version=row["version"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


class SQLiteTaskRepository:
    """Durable task repository for process and restart recovery."""

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

    def __init__(
        self,
        database: str | sqlite3.Connection,
        event_sink: Callable[[GovernanceEvent], None] | None = None,
    ) -> None:
        self._connection = _connection(database)
        self._event_sink = event_sink
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                owner_json TEXT NOT NULL,
                goal TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

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
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO tasks
                    (task_id, owner_json, goal, steps_json, status, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    _principal_json(task.owner),
                    task.goal,
                    _steps_json(task.steps),
                    task.status.value,
                    task.version,
                    _timestamp(task.created_at),
                    _timestamp(task.updated_at),
                ),
            )
        self._emit(
            GovernanceEvent(
                org_id=principal.org_id,
                event_type="task.created",
                actor_user_id=principal.user_id,
                decision="allow",
                reason="Task created.",
                task_id=task.task_id,
                payload={"status": task.status.value, "version": task.version},
            )
        )
        return task

    def get(self, principal: Principal, task_id: str) -> Task:
        row = self._connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFound("Task was not found.")
        task = _task_from_row(row)
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
        with self._connection:
            row = self._connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFound("Task was not found.")
            current = _task_from_row(row)
            if (
                current.owner.org_id != principal.org_id
                or current.owner.user_id != principal.user_id
            ):
                raise TaskScopeError("Task is not available to this principal.")
            if current.version != expected_version:
                raise TaskConflict("Task version is stale.")
            if target not in self._TRANSITIONS[current.status]:
                raise InvalidTaskTransition(
                    f"Cannot transition task from {current.status} to {target}."
                )
            updated = current.with_status(target)
            cursor = self._connection.execute(
                """
                UPDATE tasks
                SET status = ?, version = ?, updated_at = ?
                WHERE task_id = ? AND version = ?
                """,
                (
                    updated.status.value,
                    updated.version,
                    _timestamp(updated.updated_at),
                    task_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskConflict("Task version is stale.")
        self._emit(
            GovernanceEvent(
                org_id=principal.org_id,
                event_type="task.transitioned",
                actor_user_id=principal.user_id,
                decision="allow",
                reason="Task status transitioned.",
                task_id=task_id,
                payload={
                    "from_status": current.status.value,
                    "to_status": updated.status.value,
                    "version": updated.version,
                },
            )
        )
        return updated

    def _emit(self, event: GovernanceEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
