"""SQLite-backed append-only governance ledger."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone

from execution_kernel import Principal

from .ledger import LedgerConflict
from .models import GovernanceEvent


def _connection(database: str | sqlite3.Connection) -> sqlite3.Connection:
    connection = database if isinstance(database, sqlite3.Connection) else sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _event_json(event: GovernanceEvent) -> str:
    return json.dumps(
        {
            "org_id": event.org_id,
            "event_type": event.event_type,
            "actor_user_id": event.actor_user_id,
            "decision": event.decision,
            "reason": event.reason,
            "task_id": event.task_id,
            "approval_id": event.approval_id,
            "capability": event.capability,
            "payload": dict(event.payload),
            "event_id": event.event_id,
            "occurred_at": _timestamp(event.occurred_at),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _event_from_row(row: sqlite3.Row) -> GovernanceEvent:
    return GovernanceEvent(
        org_id=row["org_id"],
        event_type=row["event_type"],
        actor_user_id=row["actor_user_id"],
        decision=row["decision"],
        reason=row["reason"],
        task_id=row["task_id"],
        approval_id=row["approval_id"],
        capability=row["capability"],
        payload=json.loads(row["payload_json"]),
        event_id=row["event_id"],
        occurred_at=_datetime(row["occurred_at"]),
    )


class SQLiteGovernanceLedger:
    """Durable append-only ledger with idempotent event identity."""

    def __init__(self, database: str | sqlite3.Connection) -> None:
        self._connection = _connection(database)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS governance_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                org_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                task_id TEXT,
                approval_id TEXT,
                capability TEXT,
                payload_json TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def append(self, event: GovernanceEvent) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO governance_events
                        (event_id, org_id, event_type, actor_user_id, decision, reason,
                         task_id, approval_id, capability, payload_json, occurred_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.org_id,
                        event.event_type,
                        event.actor_user_id,
                        event.decision,
                        event.reason,
                        event.task_id,
                        event.approval_id,
                        event.capability,
                        json.dumps(
                            dict(event.payload),
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        _timestamp(event.occurred_at),
                    ),
                )
        except sqlite3.IntegrityError:
            row = self._connection.execute(
                "SELECT * FROM governance_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if row is None or _event_json(_event_from_row(row)) != _event_json(event):
                raise LedgerConflict("Event ID is already bound to different data.")

    def events_for(
        self,
        principal: Principal,
        *,
        task_id: str | None = None,
    ) -> tuple[GovernanceEvent, ...]:
        if task_id is not None and not task_id.strip():
            raise ValueError("task_id must not be empty when provided")
        if task_id is None:
            rows = self._connection.execute(
                """
                SELECT * FROM governance_events
                WHERE org_id = ?
                ORDER BY sequence
                """,
                (principal.org_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM governance_events
                WHERE org_id = ? AND task_id = ?
                ORDER BY sequence
                """,
                (principal.org_id, task_id),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)
