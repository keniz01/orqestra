"""Model-independent contracts for governed, read-only workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


_FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
        "access_token",
        "api_key",
        "connection_string",
        "dsn",
        "sql",
        "query",
    }
)


def _reject_ungoverned_input(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_INPUT_KEYS:
                raise ValueError(f"{path} must not contain direct {normalized} input")
            _reject_ungoverned_input(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple, frozenset)):
        for index, nested in enumerate(value):
            _reject_ungoverned_input(nested, f"{path}[{index}]")


class WorkflowResultState(StrEnum):
    """Terminal and non-terminal states exposed by the workflow boundary."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class CapabilityResultState(StrEnum):
    """Outcome supplied by a governed capability adapter."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class Evidence:
    """A provenance record supplied by a governed capability."""

    source: str
    reference: str
    capability: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("source", "reference", "capability"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone information")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ReadPlanStep:
    """A typed capability request; it is not executable SQL or a credential bag."""

    step_id: str
    capability: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _required_text(self.step_id, "step_id"))
        object.__setattr__(
            self, "capability", _required_text(self.capability, "capability")
        )
        arguments = dict(self.arguments)
        _reject_ungoverned_input(arguments, "arguments")
        object.__setattr__(self, "arguments", arguments)


@dataclass(frozen=True, slots=True)
class ReadWorkflowPlan:
    """A model-independent goal and ordered set of typed read steps."""

    goal: str
    steps: tuple[ReadPlanStep, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _required_text(self.goal, "goal"))
        if not self.steps:
            raise ValueError("steps must not be empty")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        object.__setattr__(self, "steps", tuple(self.steps))


@dataclass(frozen=True, slots=True)
class GovernedCapabilityResult:
    """An injected result from an already authorized capability invocation."""

    step_id: str
    capability: str
    state: CapabilityResultState
    value: Any = None
    evidence: tuple[Evidence, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _required_text(self.step_id, "step_id"))
        object.__setattr__(
            self, "capability", _required_text(self.capability, "capability")
        )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class ReadWorkflowResult:
    """The runner's bounded, evidence-backed workflow outcome."""

    state: WorkflowResultState
    values: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    confidence: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.state is WorkflowResultState.COMPLETED:
            if not self.evidence:
                raise ValueError("completed results require evidence")
            if self.confidence is None:
                raise ValueError("completed results require confidence")
