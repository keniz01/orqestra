"""In-memory reference implementation of the memory service contract."""

from __future__ import annotations

from datetime import datetime, timezone

from execution_kernel import Principal

from .models import (
    MemoryAuthorizer,
    MemoryClassification,
    MemoryRecord,
    MemoryScope,
)


class MemoryAuthorizationError(PermissionError):
    """Raised when a principal crosses a memory authorization boundary."""


class MemoryNotFound(LookupError):
    """Raised when a memory record does not exist."""


class InMemoryMemoryStore:
    """Bounded reference store for local development and contract tests."""

    def __init__(
        self,
        *,
        authorizer: MemoryAuthorizer | None = None,
        max_results: int = 100,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self._records: dict[str, MemoryRecord] = {}
        self._authorizer = authorizer or MemoryAuthorizer()
        self._max_results = max_results

    def write(self, principal: Principal, record: MemoryRecord) -> MemoryRecord:
        if not self._authorizer.can_write(principal, record):
            raise MemoryAuthorizationError("Memory write is not authorized.")
        self._records[record.memory_id] = record
        return record

    def get(self, principal: Principal, memory_id: str) -> MemoryRecord:
        record = self._records.get(memory_id)
        if record is None:
            raise MemoryNotFound("Memory record was not found.")
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
        records = [
            record
            for record in self._records.values()
            if record.retention.is_active(now)
            and (scope is None or record.scope is scope)
            and (classification is None or record.classification is classification)
            and self._authorizer.can_read(principal, record)
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return tuple(records[:limit])
