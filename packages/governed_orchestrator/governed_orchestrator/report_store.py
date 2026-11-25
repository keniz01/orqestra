"""Tenant-scoped durable storage for evidence-backed workflow reports."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from read_workflows import (
    CritiqueState,
    ReadWorkflowReport,
    WorkflowCritique,
    WorkflowResultState,
)


class WorkflowReportStore(Protocol):
    def save(self, org_id: str, report: ReadWorkflowReport) -> None:
        ...

    def get(self, org_id: str, trace_id: str) -> ReadWorkflowReport | None:
        ...


class InMemoryWorkflowReportStore:
    """Reference report store with explicit tenant isolation."""

    def __init__(self) -> None:
        self._reports: dict[tuple[str, str], ReadWorkflowReport] = {}

    def save(self, org_id: str, report: ReadWorkflowReport) -> None:
        self._reports[(org_id, report.trace_id)] = report

    def get(self, org_id: str, trace_id: str) -> ReadWorkflowReport | None:
        return self._reports.get((org_id, trace_id))


class SQLiteWorkflowReportStore:
    """Durable tenant-scoped report store for replay and audit surfaces."""

    def __init__(self, database: str | sqlite3.Connection) -> None:
        self._connection = (
            database
            if isinstance(database, sqlite3.Connection)
            else sqlite3.connect(database)
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_reports (
                org_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                report_json TEXT NOT NULL,
                PRIMARY KEY (org_id, trace_id)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def save(self, org_id: str, report: ReadWorkflowReport) -> None:
        payload = {
            "goal": report.goal,
            "state": report.state.value,
            "values": _jsonable(report.values),
            "citations": list(report.citations),
            "query_hashes": list(report.query_hashes),
            "confidence": report.confidence,
            "trace_id": report.trace_id,
            "critique": (
                {
                    "state": report.critique.state.value,
                    "reason": report.critique.reason,
                    "confidence": report.critique.confidence,
                }
                if report.critique is not None
                else None
            ),
        }
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO workflow_reports (org_id, trace_id, report_json)
                VALUES (?, ?, ?)
                ON CONFLICT (org_id, trace_id) DO UPDATE SET
                    report_json = excluded.report_json
                """,
                (org_id, report.trace_id, json.dumps(payload, sort_keys=True)),
            )

    def get(self, org_id: str, trace_id: str) -> ReadWorkflowReport | None:
        row = self._connection.execute(
            """
            SELECT report_json
            FROM workflow_reports
            WHERE org_id = ? AND trace_id = ?
            """,
            (org_id, trace_id),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["report_json"])
        critique = payload.get("critique")
        return ReadWorkflowReport(
            goal=payload["goal"],
            state=WorkflowResultState(payload["state"]),
            values=_from_jsonable(payload["values"]),
            citations=tuple(payload["citations"]),
            query_hashes=tuple(payload["query_hashes"]),
            confidence=payload["confidence"],
            trace_id=payload["trace_id"],
            critique=(
                WorkflowCritique(
                    state=CritiqueState(critique["state"]),
                    reason=critique["reason"],
                    confidence=critique["confidence"],
                )
                if critique is not None
                else None
            ),
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return {"__tuple__": [_jsonable(item) for item in value]}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _from_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__tuple__"}:
            return tuple(_from_jsonable(item) for item in value["__tuple__"])
        return {key: _from_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_jsonable(item) for item in value]
    return value
