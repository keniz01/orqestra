"""SQLite-backed approval repository preserving approval invariants."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from execution_kernel import Principal
from governance import GovernanceEvent

from .models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    principal_can_approve,
)
from .store import (
    ApprovalConflict,
    ApprovalNotFound,
    ApprovalScopeError,
    InvalidApprovalDecision,
)


def _connection(database: str | sqlite3.Connection) -> sqlite3.Connection:
    connection = database if isinstance(database, sqlite3.Connection) else sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _request_from_row(row: sqlite3.Row) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=row["approval_id"],
        org_id=row["org_id"],
        task_id=row["task_id"],
        capability=row["capability"],
        requester_id=row["requester_id"],
        reason=row["reason"],
        expires_at=_datetime(row["expires_at"]),
        status=ApprovalStatus(row["status"]),
        approver_id=row["approver_id"],
        version=row["version"],
        created_at=_datetime(row["created_at"]),
        decided_at=_datetime(row["decided_at"]) if row["decided_at"] else None,
    )


class SQLiteApprovalRepository:
    """Durable approval repository with tenant and separation-of-duties checks."""

    def __init__(
        self,
        database: str | sqlite3.Connection,
        event_sink: Callable[[GovernanceEvent], None] | None = None,
    ) -> None:
        self._connection = _connection(database)
        self._event_sink = event_sink
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                approval_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                requester_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL,
                approver_id TEXT,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def create(
        self,
        requester: Principal,
        *,
        task_id: str,
        capability: str,
        reason: str,
        expires_at: datetime,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_id=str(uuid4()),
            org_id=requester.org_id,
            task_id=task_id,
            capability=capability,
            requester_id=requester.user_id,
            reason=reason,
            expires_at=expires_at,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO approval_requests
                    (approval_id, org_id, task_id, capability, requester_id, reason,
                     expires_at, status, approver_id, version, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.approval_id,
                    request.org_id,
                    request.task_id,
                    request.capability,
                    request.requester_id,
                    request.reason,
                    _timestamp(request.expires_at),
                    request.status.value,
                    request.approver_id,
                    request.version,
                    _timestamp(request.created_at),
                    None,
                ),
            )
        self._emit(
            GovernanceEvent(
                org_id=request.org_id,
                event_type="approval.created",
                actor_user_id=request.requester_id,
                decision="allow",
                reason="Approval request created.",
                task_id=request.task_id,
                approval_id=request.approval_id,
                capability=request.capability,
                payload={"version": request.version},
            )
        )
        return request

    def get(self, principal: Principal, approval_id: str) -> ApprovalRequest:
        row = self._connection.execute(
            "SELECT * FROM approval_requests WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise ApprovalNotFound("Approval request was not found.")
        request = _request_from_row(row)
        if request.org_id != principal.org_id:
            raise ApprovalScopeError("Approval request is not available to this tenant.")
        if (
            request.status is ApprovalStatus.PENDING
            and datetime.now(timezone.utc) >= request.expires_at
        ):
            expired = request.decided(ApprovalStatus.EXPIRED, "system")
            with self._connection:
                self._connection.execute(
                    """
                    UPDATE approval_requests
                    SET status = ?, approver_id = ?, version = ?, decided_at = ?
                    WHERE approval_id = ? AND version = ?
                    """,
                    (
                        expired.status.value,
                        expired.approver_id,
                        expired.version,
                        _timestamp(expired.decided_at),
                        approval_id,
                        request.version,
                    ),
                )
            self._emit(
                GovernanceEvent(
                    org_id=expired.org_id,
                    event_type="approval.expired",
                    actor_user_id="system",
                    decision=expired.status.value,
                    reason="Approval request expired.",
                    task_id=expired.task_id,
                    approval_id=expired.approval_id,
                    capability=expired.capability,
                    payload={"version": expired.version},
                )
            )
            return expired
        return request

    def decide(
        self,
        approver: Principal,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        expected_version: int,
    ) -> ApprovalRequest:
        request = self.get(approver, approval_id)
        if request.version != expected_version:
            raise ApprovalConflict("Approval request version is stale.")
        if request.status is not ApprovalStatus.PENDING:
            raise InvalidApprovalDecision("Approval request is no longer pending.")
        if not principal_can_approve(approver, request):
            raise ApprovalScopeError("Requester cannot approve their own request.")
        if decision is ApprovalDecision.APPROVE:
            status = ApprovalStatus.APPROVED
        elif decision is ApprovalDecision.REJECT:
            status = ApprovalStatus.REJECTED
        else:
            raise InvalidApprovalDecision("Unsupported approval decision.")
        updated = request.decided(status, approver.user_id)
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, approver_id = ?, version = ?, decided_at = ?
                WHERE approval_id = ? AND version = ? AND status = ?
                """,
                (
                    updated.status.value,
                    updated.approver_id,
                    updated.version,
                    _timestamp(updated.decided_at),
                    approval_id,
                    expected_version,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ApprovalConflict("Approval request version is stale.")
        self._emit(
            GovernanceEvent(
                org_id=updated.org_id,
                event_type="approval.decided",
                actor_user_id=approver.user_id,
                decision=updated.status.value,
                reason="Approval request decided.",
                task_id=updated.task_id,
                approval_id=updated.approval_id,
                capability=updated.capability,
                payload={"version": updated.version},
            )
        )
        return updated

    def is_approved(
        self,
        principal: Principal,
        approval_id: str,
        *,
        task_id: str,
        capability: str,
    ) -> bool:
        request = self.get(principal, approval_id)
        return (
            request.task_id == task_id
            and request.capability == capability
            and request.is_active()
        )

    def _emit(self, event: GovernanceEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
