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
class WorkflowBudget:
    """Bounds applied to a workflow before capabilities are invoked."""

    max_steps: int = 32
    max_evidence: int = 128

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_evidence < 1:
            raise ValueError("max_evidence must be positive")


@dataclass(frozen=True, slots=True)
class Evidence:
    """A provenance record supplied by a governed capability."""

    source: str
    reference: str
    capability: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)
    query_hash: str | None = None

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
        if self.query_hash is not None:
            object.__setattr__(
                self, "query_hash", _required_text(self.query_hash, "query_hash")
            )


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
    budget: WorkflowBudget = field(default_factory=WorkflowBudget)

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _required_text(self.goal, "goal"))
        if not self.steps:
            raise ValueError("steps must not be empty")
        if not isinstance(self.budget, WorkflowBudget):
            raise ValueError("budget must be a WorkflowBudget")
        if len(self.steps) > self.budget.max_steps:
            raise ValueError("steps exceed the workflow budget")
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
    query_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _required_text(self.step_id, "step_id"))
        object.__setattr__(
            self, "capability", _required_text(self.capability, "capability")
        )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.query_hash is not None:
            object.__setattr__(
                self, "query_hash", _required_text(self.query_hash, "query_hash")
            )


class CritiqueState(StrEnum):
    """Outcome of a bounded result critique."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class WorkflowCritique:
    """Structured quality decision for an otherwise governed result."""

    state: CritiqueState
    reason: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ReadWorkflowResult:
    """The runner's bounded, evidence-backed workflow outcome."""

    state: WorkflowResultState
    values: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    confidence: float | None = None
    reason: str | None = None
    critique: WorkflowCritique | None = None
    trace_id: str | None = None
    query_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self, "query_hashes", tuple(dict.fromkeys(self.query_hashes))
        )
        if not self.query_hashes:
            object.__setattr__(
                self,
                "query_hashes",
                tuple(
                    dict.fromkeys(
                        item.query_hash
                        for item in self.evidence
                        if item.query_hash is not None
                    )
                ),
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.trace_id is not None:
            object.__setattr__(
                self, "trace_id", _required_text(self.trace_id, "trace_id")
            )
        if self.state is WorkflowResultState.COMPLETED:
            if not self.evidence:
                raise ValueError("completed results require evidence")
            if self.confidence is None:
                raise ValueError("completed results require confidence")
            if self.critique is not None and (
                self.critique.state is not CritiqueState.ACCEPTED
            ):
                raise ValueError("completed results require an accepted critique")

    @property
    def citations(self) -> tuple[str, ...]:
        """Return unique provenance references in stable order."""

        return tuple(dict.fromkeys(item.reference for item in self.evidence))


@dataclass(frozen=True, slots=True)
class ReadWorkflowReport:
    """Evidence-backed, replay-oriented presentation of a workflow result."""

    goal: str
    state: WorkflowResultState
    values: Mapping[str, Any]
    citations: tuple[str, ...]
    query_hashes: tuple[str, ...]
    confidence: float | None
    trace_id: str
    critique: WorkflowCritique | None = None

    @classmethod
    def from_result(
        cls, goal: str, result: ReadWorkflowResult, *, trace_id: str
    ) -> "ReadWorkflowReport":
        return cls(
            goal=_required_text(goal, "goal"),
            state=result.state,
            values=result.values,
            citations=result.citations,
            query_hashes=result.query_hashes,
            confidence=result.confidence,
            trace_id=_required_text(trace_id, "trace_id"),
            critique=result.critique,
        )
