from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from approval_plane import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalRepository,
    ApprovalScopeError,
    ApprovalStatus,
    ApprovalStore,
    InMemoryApprovalRepository,
    SQLiteApprovalRepository,
)
from execution_kernel import Principal


def principal(user_id: str, org_id: str = "org-1") -> Principal:
    return Principal(user_id=user_id, org_id=org_id, roles=frozenset({"admin"}))


def create_request(store: ApprovalStore):
    return store.create(
        principal("requester"),
        task_id="task-1",
        capability="data.export_result",
        reason="Export approved customer analysis.",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def test_approval_requires_different_principal_and_is_tenant_scoped():
    store = ApprovalStore()
    request = create_request(store)

    with pytest.raises(ApprovalScopeError, match="own request"):
        store.decide(
            principal("requester"),
            request.approval_id,
            ApprovalDecision.APPROVE,
            expected_version=request.version,
        )

    approved = store.decide(
        principal("approver"),
        request.approval_id,
        ApprovalDecision.APPROVE,
        expected_version=request.version,
    )

    assert approved.status is ApprovalStatus.APPROVED
    assert store.is_approved(
        principal("requester"),
        request.approval_id,
        task_id="task-1",
        capability="data.export_result",
    )

    with pytest.raises(ApprovalScopeError):
        store.get(principal("other-user", "other-org"), request.approval_id)


def test_stale_and_expired_approvals_cannot_be_used():
    store = ApprovalStore()
    request = create_request(store)

    with pytest.raises(ApprovalConflict):
        store.decide(
            principal("approver"),
            request.approval_id,
            ApprovalDecision.REJECT,
            expected_version=request.version + 1,
        )

    expired = store.create(
        principal("requester"),
        task_id="task-2",
        capability="data.export_result",
        reason="Expired request.",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    assert store.get(principal("approver"), expired.approval_id).status is ApprovalStatus.EXPIRED
    assert not store.is_approved(
        principal("requester"),
        expired.approval_id,
        task_id="task-2",
        capability="data.export_result",
    )


def test_approval_store_emits_governance_events():
    events = []
    store = ApprovalStore(event_sink=events.append)
    request = create_request(store)

    store.decide(
        principal("approver"),
        request.approval_id,
        ApprovalDecision.REJECT,
        expected_version=request.version,
    )

    assert [event.event_type for event in events] == [
        "approval.created",
        "approval.decided",
    ]
    assert all(event.org_id == "org-1" for event in events)


def test_in_memory_approval_adapter_satisfies_repository_contract():
    store = InMemoryApprovalRepository()

    assert isinstance(store, ApprovalRepository)
    assert isinstance(store, ApprovalStore)


def test_sqlite_approval_repository_preserves_decisions_after_reopen(tmp_path):
    database = tmp_path / "approvals.sqlite"
    first_store = SQLiteApprovalRepository(str(database))
    request = create_request(first_store)
    approved = first_store.decide(
        principal("approver"),
        request.approval_id,
        ApprovalDecision.APPROVE,
        expected_version=request.version,
    )
    first_store.close()

    second_store = SQLiteApprovalRepository(str(database))
    restored = second_store.get(principal("requester"), request.approval_id)
    assert restored.status is ApprovalStatus.APPROVED
    assert restored.version == approved.version
    assert second_store.is_approved(
        principal("requester"),
        request.approval_id,
        task_id="task-1",
        capability="data.export_result",
    )
    second_store.close()
