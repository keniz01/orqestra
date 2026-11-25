from datetime import datetime, timedelta, timezone

import pytest

from execution_kernel import Principal
from memory_service import (
    InMemoryMemoryStore,
    MemoryAuthorizationError,
    MemoryClassification,
    MemoryNotFound,
    MemoryProvenance,
    MemoryRecord,
    MemoryRetention,
    MemoryScope,
    RetentionClass,
)


def principal(user_id: str, org_id: str = "org-1") -> Principal:
    return Principal(user_id=user_id, org_id=org_id)


def record(
    *,
    org_id: str = "org-1",
    scope: MemoryScope = MemoryScope.TENANT,
    owner_user_id: str | None = None,
    classification: MemoryClassification = MemoryClassification.INTERNAL,
    retention: MemoryRetention | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        org_id=org_id,
        scope=scope,
        scope_id="scope-1",
        owner_user_id=owner_user_id,
        content="A bounded memory.",
        classification=classification,
        retention=retention
        or MemoryRetention(RetentionClass.STANDARD),
        provenance=MemoryProvenance(
            source="task_observation",
            source_id="task-1",
            recorded_by="user-1",
            reason="Capture a verified observation.",
        ),
    )


def test_memory_writes_and_reads_are_tenant_and_scope_isolated():
    store = InMemoryMemoryStore()
    tenant_memory = store.write(principal("writer"), record())
    private_memory = store.write(
        principal("writer"),
        record(scope=MemoryScope.USER, owner_user_id="writer"),
    )

    assert store.get(principal("reader"), tenant_memory.memory_id) == tenant_memory
    assert store.retrieve(principal("reader")) == (tenant_memory,)
    with pytest.raises(MemoryAuthorizationError):
        store.get(principal("other", "org-2"), tenant_memory.memory_id)
    with pytest.raises(MemoryAuthorizationError):
        store.get(principal("reader"), private_memory.memory_id)


def test_classification_and_retention_metadata_are_validated():
    with pytest.raises(ValueError, match="classification"):
        MemoryRecord(
            org_id="org-1",
            scope=MemoryScope.TENANT,
            scope_id="scope-1",
            content="content",
            classification="secret",  # type: ignore[arg-type]
            retention=MemoryRetention(RetentionClass.STANDARD),
            provenance=record().provenance,
        )
    with pytest.raises(ValueError, match="requires expires_at"):
        MemoryRetention(RetentionClass.EPHEMERAL)
    with pytest.raises(ValueError, match="timezone"):
        MemoryRetention(RetentionClass.TASK, datetime.now())


def test_provenance_is_required():
    with pytest.raises(TypeError):
        MemoryRecord(  # type: ignore[call-arg]
            org_id="org-1",
            scope=MemoryScope.TENANT,
            scope_id="scope-1",
            content="content",
            classification=MemoryClassification.INTERNAL,
            retention=MemoryRetention(RetentionClass.STANDARD),
        )
    with pytest.raises(ValueError, match="source"):
        MemoryProvenance("", "source-1", "user-1", "reason")


def test_retrieval_is_bounded_and_excludes_expired_records():
    store = InMemoryMemoryStore(max_results=2)
    for _ in range(3):
        store.write(principal("writer"), record())
    expired = record(
        retention=MemoryRetention(
            RetentionClass.TASK,
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    store.write(principal("writer"), expired)

    assert len(store.retrieve(principal("reader"), limit=2)) == 2
    assert expired.memory_id not in {
        item.memory_id for item in store.retrieve(principal("reader"), limit=2)
    }
    with pytest.raises(ValueError, match="between"):
        store.retrieve(principal("reader"), limit=3)
