"""SQLite-backed tenant-scoped memory repository."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone

from execution_kernel import Principal

from .models import (
    MemoryAuthorizer,
    MemoryClassification,
    MemoryProvenance,
    MemoryRecord,
    MemoryRetention,
    MemoryScope,
    RetentionClass,
)
from .store import MemoryAuthorizationError, MemoryNotFound


def _connection(database: str | sqlite3.Connection) -> sqlite3.Connection:
    connection = database if isinstance(database, sqlite3.Connection) else sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        org_id=row["org_id"],
        scope=MemoryScope(row["scope"]),
        scope_id=row["scope_id"],
        content=row["content"],
        classification=MemoryClassification(row["classification"]),
        retention=MemoryRetention(
            policy=RetentionClass(row["retention_policy"]),
            expires_at=_datetime(row["expires_at"]) if row["expires_at"] else None,
        ),
        provenance=MemoryProvenance(
            source=row["provenance_source"],
            source_id=row["provenance_source_id"],
            recorded_by=row["provenance_recorded_by"],
            reason=row["provenance_reason"],
        ),
        owner_user_id=row["owner_user_id"],
        metadata=json.loads(row["metadata_json"]),
        memory_id=row["memory_id"],
        created_at=_datetime(row["created_at"]),
    )


class SQLiteMemoryStore:
    """Durable bounded memory store with the reference authorization contract."""

    def __init__(
        self,
        database: str | sqlite3.Connection,
        *,
        authorizer: MemoryAuthorizer | None = None,
        max_results: int = 100,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self._connection = _connection(database)
        self._authorizer = authorizer or MemoryAuthorizer()
        self._max_results = max_results
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                content TEXT NOT NULL,
                classification TEXT NOT NULL,
                retention_policy TEXT NOT NULL,
                expires_at TEXT,
                provenance_source TEXT NOT NULL,
                provenance_source_id TEXT NOT NULL,
                provenance_recorded_by TEXT NOT NULL,
                provenance_reason TEXT NOT NULL,
                owner_user_id TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def write(self, principal: Principal, record: MemoryRecord) -> MemoryRecord:
        if not self._authorizer.can_write(principal, record):
            raise MemoryAuthorizationError("Memory write is not authorized.")
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO memories
                    (memory_id, org_id, scope, scope_id, content, classification,
                     retention_policy, expires_at, provenance_source, provenance_source_id,
                     provenance_recorded_by, provenance_reason, owner_user_id,
                     metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.org_id,
                    record.scope.value,
                    record.scope_id,
                    record.content,
                    record.classification.value,
                    record.retention.policy.value,
                    _timestamp(record.retention.expires_at)
                    if record.retention.expires_at
                    else None,
                    record.provenance.source,
                    record.provenance.source_id,
                    record.provenance.recorded_by,
                    record.provenance.reason,
                    record.owner_user_id,
                    json.dumps(dict(record.metadata), separators=(",", ":"), sort_keys=True),
                    _timestamp(record.created_at),
                ),
            )
        return record

    def get(self, principal: Principal, memory_id: str) -> MemoryRecord:
        row = self._connection.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            raise MemoryNotFound("Memory record was not found.")
        record = _record_from_row(row)
        if not self._authorizer.can_read(principal, record):
            raise MemoryAuthorizationError("Memory record is not available to this principal.")
        if not record.retention.is_active():
            raise MemoryNotFound("Memory record was not found.")
        return record

    def retrieve(
        self,
        principal: Principal,
        *,
        scope: MemoryScope | None = None,
        classification: MemoryClassification | None = None,
        limit: int = 10,
    ) -> tuple[MemoryRecord, ...]:
        if limit < 1 or limit > self._max_results:
            raise ValueError(f"limit must be between 1 and {self._max_results}")
        now = datetime.now(timezone.utc)
        clauses = ["(expires_at IS NULL OR expires_at > ?)", "org_id = ?"]
        values: list[str] = [_timestamp(now), principal.org_id]
        if scope is not None:
            clauses.append("scope = ?")
            values.append(scope.value)
        if classification is not None:
            clauses.append("classification = ?")
            values.append(classification.value)
        rows = self._connection.execute(
            f"""
            SELECT * FROM memories
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*values, limit),
        ).fetchall()
        records = [
            record
            for row in rows
            if self._authorizer.can_read(principal, record := _record_from_row(row))
        ]
        return tuple(records)
