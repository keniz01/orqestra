"""Approval contracts for higher-risk capability execution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum

from execution_kernel import Principal


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """A tenant-scoped, time-bounded request for delegated authority."""

    approval_id: str
    org_id: str
    task_id: str
    capability: str
    requester_id: str
    reason: str
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    approver_id: str | None = None
    version: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "org_id",
            "task_id",
            "capability",
            "requester_id",
            "reason",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if self.version < 0:
            raise ValueError("version must not be negative")

    def is_active(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(timezone.utc)
        return self.status is ApprovalStatus.APPROVED and current_time < self.expires_at

    def decided(
        self,
        status: ApprovalStatus,
        approver_id: str,
        decided_at: datetime | None = None,
    ) -> "ApprovalRequest":
        return replace(
            self,
            status=status,
            approver_id=approver_id,
            version=self.version + 1,
            decided_at=decided_at or datetime.now(timezone.utc),
        )


def principal_can_approve(principal: Principal, request: ApprovalRequest) -> bool:
    """Require same-tenant approval by a different principal."""

    return (
        principal.org_id == request.org_id
        and principal.user_id != request.requester_id
    )
