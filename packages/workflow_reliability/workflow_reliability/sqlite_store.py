"""SQLite-backed workflow reliability repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

from .contracts import Cancellation, Checkpoint, IdempotencyRecord, Lease, _text
from .store import (
    CheckpointConflict,
    CheckpointNotFound,
    IdempotencyConflict,
    LeaseConflict,
    LeaseNotFound,
    LeaseOwnershipError,
    WorkflowCancelled,
)

T = TypeVar("T")


def _connection(database: str | sqlite3.Connection) -> sqlite3.Connection:
    if isinstance(database, sqlite3.Connection):
        connection = database
    else:
        connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Durable workflow state must be JSON serializable.") from exc


class SQLiteReliabilityStore:
    """Durable leases, idempotency, cancellation, and checkpoint state."""

    def __init__(self, database: str | sqlite3.Connection) -> None:
        self._connection = _connection(database)
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_leases (
                workflow_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_idempotency (
                key TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_cancellations (
                workflow_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                workflow_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                checkpoint_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (workflow_id, version)
            );
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def get_lease(self, workflow_id: str, *, now: datetime | None = None) -> Lease | None:
        _text("workflow_id", workflow_id)
        row = self._connection.execute(
            "SELECT * FROM workflow_leases WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        lease = Lease(
            workflow_id=row["workflow_id"],
            lease_id=row["lease_id"],
            owner_id=row["owner_id"],
            expires_at=_datetime(row["expires_at"]),
            version=row["version"],
        )
        current = now or datetime.now(timezone.utc)
        if not lease.is_active(current):
            with self._connection:
                self._connection.execute(
                    "DELETE FROM workflow_leases WHERE workflow_id = ?",
                    (workflow_id,),
                )
            return None
        return lease

    def acquire_lease(
        self,
        workflow_id: str,
        owner_id: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> Lease:
        current = now or datetime.now(timezone.utc)
        if ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        try:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM workflow_leases WHERE workflow_id = ? AND expires_at <= ?",
                    (workflow_id, _timestamp(current)),
                )
                lease_id = _text("lease_id", uuid4().hex)
                self._connection.execute(
                    """
                    INSERT INTO workflow_leases
                        (workflow_id, lease_id, owner_id, expires_at, version)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (
                        workflow_id,
                        lease_id,
                        owner_id,
                        _timestamp(current + ttl),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise LeaseConflict("Workflow already has an active lease.") from exc
        return Lease(
            workflow_id=workflow_id,
            lease_id=lease_id,
            owner_id=owner_id,
            expires_at=current + ttl,
        )

    def renew_lease(
        self,
        workflow_id: str,
        lease_id: str,
        owner_id: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> Lease:
        current = now or datetime.now(timezone.utc)
        lease = self._owned_lease(workflow_id, lease_id, owner_id, current)
        if ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        updated = Lease(
            workflow_id=workflow_id,
            lease_id=lease.lease_id,
            owner_id=lease.owner_id,
            expires_at=current + ttl,
            version=lease.version + 1,
        )
        with self._connection:
            self._connection.execute(
                """
                UPDATE workflow_leases
                SET expires_at = ?, version = ?
                WHERE workflow_id = ? AND lease_id = ? AND owner_id = ? AND version = ?
                """,
                (
                    _timestamp(updated.expires_at),
                    updated.version,
                    workflow_id,
                    lease_id,
                    owner_id,
                    lease.version,
                ),
            )
        return updated

    def release_lease(
        self,
        workflow_id: str,
        lease_id: str,
        owner_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self._owned_lease(workflow_id, lease_id, owner_id, now or datetime.now(timezone.utc))
        with self._connection:
            self._connection.execute(
                "DELETE FROM workflow_leases WHERE workflow_id = ?",
                (workflow_id,),
            )

    def _owned_lease(
        self,
        workflow_id: str,
        lease_id: str,
        owner_id: str,
        now: datetime,
    ) -> Lease:
        lease = self.get_lease(workflow_id, now=now)
        if lease is None:
            raise LeaseNotFound("Workflow lease was not found or has expired.")
        if lease.lease_id != lease_id or lease.owner_id != owner_id:
            raise LeaseOwnershipError("Lease ownership is stale or invalid.")
        return lease

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        _text("key", key)
        row = self._connection.execute(
            "SELECT * FROM workflow_idempotency WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            request_hash=row["request_hash"],
            response=json.loads(row["response_json"]),
            created_at=_datetime(row["created_at"]),
        )

    def execute_idempotent(
        self,
        key: str,
        request_hash: str,
        operation: Callable[[], T],
    ) -> T:
        _text("key", key)
        _text("request_hash", request_hash, max_length=512)
        existing = self.get_idempotency(key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflict("Idempotency key has a different request.")
            return deepcopy(existing.response)
        response = operation()
        record = IdempotencyRecord(key=key, request_hash=request_hash, response=response)
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO workflow_idempotency
                        (key, request_hash, response_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, request_hash, _json(response), _timestamp(record.created_at)),
                )
        except sqlite3.IntegrityError:
            existing = self.get_idempotency(key)
            if existing is None or existing.request_hash != request_hash:
                raise IdempotencyConflict("Idempotency key has a different request.")
            return deepcopy(existing.response)
        return deepcopy(response)

    def request_cancellation(
        self,
        workflow_id: str,
        reason: str = "Cancellation requested.",
        *,
        now: datetime | None = None,
    ) -> Cancellation:
        _text("workflow_id", workflow_id)
        existing = self.get_cancellation(workflow_id)
        if existing is not None:
            return existing
        cancellation = Cancellation(
            workflow_id=workflow_id,
            reason=reason,
            requested_at=now or datetime.now(timezone.utc),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO workflow_cancellations
                    (workflow_id, reason, requested_at, version)
                VALUES (?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    cancellation.reason,
                    _timestamp(cancellation.requested_at),
                    cancellation.version,
                ),
            )
        return cancellation

    def get_cancellation(self, workflow_id: str) -> Cancellation | None:
        _text("workflow_id", workflow_id)
        row = self._connection.execute(
            "SELECT * FROM workflow_cancellations WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        return Cancellation(
            workflow_id=row["workflow_id"],
            reason=row["reason"],
            requested_at=_datetime(row["requested_at"]),
            version=row["version"],
        )

    def raise_if_cancelled(self, workflow_id: str) -> None:
        if self.get_cancellation(workflow_id) is not None:
            raise WorkflowCancelled("Workflow cancellation was requested.")

    def latest_checkpoint(self, workflow_id: str) -> Checkpoint | None:
        _text("workflow_id", workflow_id)
        row = self._connection.execute(
            """
            SELECT * FROM workflow_checkpoints
            WHERE workflow_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            workflow_id=row["workflow_id"],
            checkpoint_id=row["checkpoint_id"],
            version=row["version"],
            state=json.loads(row["state_json"]),
            created_at=_datetime(row["created_at"]),
        )

    def save_checkpoint(
        self,
        workflow_id: str,
        state: Mapping[str, Any],
        *,
        expected_version: int = 0,
        checkpoint_id: str | None = None,
        now: datetime | None = None,
    ) -> Checkpoint:
        current = self.latest_checkpoint(workflow_id)
        current_version = current.version if current is not None else 0
        if current_version != expected_version:
            raise CheckpointConflict("Checkpoint version is stale.")
        checkpoint = Checkpoint(
            workflow_id=workflow_id,
            checkpoint_id=checkpoint_id or uuid4().hex,
            version=current_version + 1,
            state=deepcopy(dict(state)),
            created_at=now or datetime.now(timezone.utc),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO workflow_checkpoints
                    (workflow_id, version, checkpoint_id, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    checkpoint.version,
                    checkpoint.checkpoint_id,
                    _json(checkpoint.state),
                    _timestamp(checkpoint.created_at),
                ),
            )
        return deepcopy(checkpoint)

    def get_checkpoint(self, workflow_id: str, version: int | None = None) -> Checkpoint:
        checkpoint = self.latest_checkpoint(workflow_id)
        if checkpoint is None:
            raise CheckpointNotFound("Workflow checkpoint was not found.")
        if version is None:
            return checkpoint
        row = self._connection.execute(
            """
            SELECT * FROM workflow_checkpoints
            WHERE workflow_id = ? AND version = ?
            """,
            (workflow_id, version),
        ).fetchone()
        if row is None:
            raise CheckpointNotFound("Requested checkpoint version was not found.")
        return Checkpoint(
            workflow_id=row["workflow_id"],
            checkpoint_id=row["checkpoint_id"],
            version=row["version"],
            state=json.loads(row["state_json"]),
            created_at=_datetime(row["created_at"]),
        )
