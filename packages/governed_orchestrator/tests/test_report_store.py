from __future__ import annotations

from read_workflows import (
    CritiqueState,
    ReadWorkflowReport,
    WorkflowCritique,
    WorkflowResultState,
)

from governed_orchestrator import SQLiteWorkflowReportStore


def test_sqlite_report_store_is_tenant_scoped(tmp_path):
    store = SQLiteWorkflowReportStore(str(tmp_path / "reports.sqlite"))
    report = ReadWorkflowReport(
        goal="Find revenue",
        state=WorkflowResultState.COMPLETED,
        values={"rows": ({"amount": 42},)},
        citations=("query:abc",),
        query_hashes=("abc",),
        confidence=0.9,
        trace_id="task-1",
        critique=WorkflowCritique(
            state=CritiqueState.ACCEPTED,
            reason="Evidence was sufficient.",
            confidence=0.9,
        ),
    )

    store.save("org-1", report)

    assert store.get("org-1", "task-1") == report
    assert store.get("org-2", "task-1") is None
    store.close()
