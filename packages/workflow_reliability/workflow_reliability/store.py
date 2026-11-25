"""In-memory reference implementations for workflow reliability contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

from .contracts import (
    Cancellation,
    Checkpoint,
    IdempotencyRecord,
    Lease,
    RetryPolicy,
    _aware,
    _text,
)

T = TypeVar("T")


class LeaseNotFound(LookupError):
    """Raised when a workflow has no lease."""


class LeaseConflict(RuntimeError):
    """Raised when an active lease already exists."""


class LeaseOwnershipError(PermissionError):
    """Raised when a lease operation is attempted by a stale owner."""


class IdempotencyConflict(RuntimeError):
    """Raised when a key is reused for a different request."""


class CancellationNotFound(LookupError):
    """Raised when a workflow has no cancellation request."""


class WorkflowCancelled(RuntimeError):
    """Raised when execution observes a cancellation request."""


class CheckpointConflict(RuntimeError):
    """Raised when a checkpoint version is stale."""


class CheckpointNotFound(LookupError):
    """Raised when a workflow has no checkpoint."""


def _now(value: datetime | None) -> datetime:
    return _aware(value, "now") if value is not None else datetime.now(timezone.utc)


def _ttl(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("ttl must be a positive timedelta")
    return value


class InMemoryLeaseStore:
    """Exclusive leases with expiry and owner checks."""

    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}

    def get(self, workflow_id: str, *, now: datetime | None = None) -> Lease | None:
        _text("workflow_id", workflow_id)
        lease = self._leases.get(workflow_id)
        if lease is not None and not lease.is_active(_now(now)):
            self._leases.pop(workflow_id, None)
            return None
        return lease

    def acquire(
        self,
        workflow_id: str,
        owner_id: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> Lease:
        current = _now(now)
        existing = self.get(workflow_id, now=current)
        if existing is not None:
            raise LeaseConflict("Workflow already has an active lease.")
        lease = Lease(
            workflow_id=workflow_id,
            lease_id=str(uuid4()),
            owner_id=owner_id,
            expires_at=current + _ttl(ttl),
        )
        self._leases[workflow_id] = lease
        return lease

    def renew(
        self,
        workflow_id: str,
        lease_id: str,
        owner_id: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> Lease:
        current = _now(now)
        lease = self._require_owned(workflow_id, lease_id, owner_id, current)
        renewed = Lease(
            workflow_id=lease.workflow_id,
            lease_id=lease.lease_id,
            owner_id=lease.owner_id,
            expires_at=current + _ttl(ttl),
            version=lease.version + 1,
        )
        self._leases[workflow_id] = renewed
        return renewed

    def release(
        self,
        workflow_id: str,
        lease_id: str,
        owner_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        lease = self._require_owned(workflow_id, lease_id, owner_id, _now(now))
        del self._leases[lease.workflow_id]

    def _require_owned(
        self, workflow_id: str, lease_id: str, owner_id: str, now: datetime
    ) -> Lease:
        lease = self.get(workflow_id, now=now)
        if lease is None:
            raise LeaseNotFound("Workflow lease was not found or has expired.")
        if lease.lease_id != lease_id or lease.owner_id != owner_id:
            raise LeaseOwnershipError("Lease ownership is stale or invalid.")
        return lease


class InMemoryIdempotencyStore:
    """Single-process idempotency record store with request-fingerprint checks."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, key: str) -> IdempotencyRecord | None:
        _text("key", key)
        record = self._records.get(key)
        return deepcopy(record) if record is not None else None

    def execute(
        self,
        key: str,
        request_hash: str,
        operation: Callable[[], T],
    ) -> T:
        _text("key", key)
        _text("request_hash", request_hash, max_length=512)
        existing = self._records.get(key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflict("Idempotency key has a different request.")
            return deepcopy(existing.response)
        response = operation()
        self._records[key] = IdempotencyRecord(
            key=key,
            request_hash=request_hash,
            response=deepcopy(response),
        )
        return deepcopy(response)


class InMemoryCancellationStore:
    """Idempotent cancellation requests with an explicit observation helper."""

    def __init__(self) -> None:
        self._cancellations: dict[str, Cancellation] = {}

    def request(
        self,
        workflow_id: str,
        reason: str = "Cancellation requested.",
        *,
        now: datetime | None = None,
    ) -> Cancellation:
        _text("workflow_id", workflow_id)
        existing = self._cancellations.get(workflow_id)
        if existing is not None:
            return existing
        cancellation = Cancellation(
            workflow_id=workflow_id,
            reason=reason,
            requested_at=_now(now),
        )
        self._cancellations[workflow_id] = cancellation
        return cancellation

    def get(self, workflow_id: str) -> Cancellation | None:
        _text("workflow_id", workflow_id)
        return self._cancellations.get(workflow_id)

    def raise_if_cancelled(self, workflow_id: str) -> None:
        if self.get(workflow_id) is not None:
            raise WorkflowCancelled("Workflow cancellation was requested.")


class InMemoryCheckpointStore:
    """Optimistically versioned in-memory workflow checkpoints."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}
        self._history: dict[str, dict[int, Checkpoint]] = {}

    def latest(self, workflow_id: str) -> Checkpoint | None:
        _text("workflow_id", workflow_id)
        checkpoint = self._checkpoints.get(workflow_id)
        return deepcopy(checkpoint) if checkpoint is not None else None

    def save(
        self,
        workflow_id: str,
        state: Mapping[str, Any],
        *,
        expected_version: int = 0,
        checkpoint_id: str | None = None,
        now: datetime | None = None,
    ) -> Checkpoint:
        _text("workflow_id", workflow_id)
        if expected_version < 0:
            raise ValueError("expected_version must not be negative")
        current = self._checkpoints.get(workflow_id)
        current_version = current.version if current is not None else 0
        if current_version != expected_version:
            raise CheckpointConflict("Checkpoint version is stale.")
        checkpoint = Checkpoint(
            workflow_id=workflow_id,
            checkpoint_id=checkpoint_id or str(uuid4()),
            version=current_version + 1,
            state=deepcopy(state),
            created_at=_now(now),
        )
        self._checkpoints[workflow_id] = checkpoint
        self._history.setdefault(workflow_id, {})[checkpoint.version] = checkpoint
        return deepcopy(checkpoint)

    def get(self, workflow_id: str, version: int | None = None) -> Checkpoint:
        checkpoint = self.latest(workflow_id)
        if checkpoint is None:
            raise CheckpointNotFound("Workflow checkpoint was not found.")
        if version is None:
            return checkpoint
        historical = self._history.get(workflow_id, {}).get(version)
        if historical is None:
            raise CheckpointNotFound("Requested checkpoint version was not found.")
        return deepcopy(historical)


def retry_attempts(policy: RetryPolicy, attempts: int) -> tuple[bool, float]:
    """Return whether another attempt is allowed and its bounded delay."""

    return policy.can_retry(attempts), policy.delay_for(attempts)
