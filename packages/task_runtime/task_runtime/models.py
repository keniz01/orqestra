"""Durable task and plan contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from execution_kernel import Principal


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PlanStep:
    """A typed capability invocation in a task plan."""

    step_id: str
    capability: str
    input: Mapping[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be empty")
        if not self.capability.strip():
            raise ValueError("capability must not be empty")
        object.__setattr__(self, "input", dict(self.input))


@dataclass(frozen=True, slots=True)
class Task:
    """Tenant-scoped durable task aggregate."""

    task_id: str
    owner: Principal
    goal: str
    steps: tuple[PlanStep, ...] = ()
    status: TaskStatus = TaskStatus.PENDING
    version: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.goal.strip():
            raise ValueError("goal must not be empty")
        if not self.steps:
            raise ValueError("a task must contain at least one plan step")
        if self.version < 0:
            raise ValueError("version must not be negative")

    def with_status(self, status: TaskStatus) -> "Task":
        return replace(
            self,
            status=status,
            version=self.version + 1,
            updated_at=datetime.now(timezone.utc),
        )
