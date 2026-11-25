"""Reference approval store with tenant and separation-of-duties controls."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from execution_kernel import Principal
from governance import GovernanceEvent

from .models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    principal_can_approve,
)


class ApprovalNotFound(LookupError):
    """Raised when an approval request does not exist."""


class ApprovalScopeError(PermissionError):
    """Raised when a principal crosses an approval tenant boundary."""


class ApprovalConflict(RuntimeError):
    """Raised when an approval request version is stale."""


class InvalidApprovalDecision(ValueError):
    """Raised when an approval cannot be decided."""


class ApprovalStore:
    """In-memory reference implementation for approval contract tests."""

    def __init__(
        self,
        event_sink: Callable[[GovernanceEvent], None] | None = None,
    ) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._event_sink = event_sink

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
        self._requests[request.approval_id] = request
        return request

    def get(self, principal: Principal, approval_id: str) -> ApprovalRequest:
        request = self._requests.get(approval_id)
        if request is None:
            raise ApprovalNotFound("Approval request was not found.")
        if request.org_id != principal.org_id:
            raise ApprovalScopeError("Approval request is not available to this tenant.")
        return self._expire_if_needed(request)

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
        self._requests[approval_id] = updated
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

    def _expire_if_needed(self, request: ApprovalRequest) -> ApprovalRequest:
        if (
            request.status is ApprovalStatus.PENDING
            and datetime.now(timezone.utc) >= request.expires_at
        ):
            expired = request.decided(ApprovalStatus.EXPIRED, "system")
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
            self._requests[request.approval_id] = expired
            return expired
        return request

    def _emit(self, event: GovernanceEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
