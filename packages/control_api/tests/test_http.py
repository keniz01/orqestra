from __future__ import annotations

import io
import json
from dataclasses import dataclass

from control_api import WsgiGovernedReadApplication
from execution_kernel import Principal
from read_workflows import ReadWorkflowReport, WorkflowResultState


@dataclass
class Resolver:
    principal: Principal

    def resolve(self, environ):
        return self.principal


class Control:
    def __init__(self):
        self.report = ReadWorkflowReport(
            goal="compare monthly revenue",
            state=WorkflowResultState.COMPLETED,
            values={"amount": 42},
            citations=("warehouse:revenue",),
            query_hashes=("abc123",),
            confidence=0.9,
            trace_id="task-1",
        )

    def submit(self, principal, request):
        return type(
            "Response",
            (),
            {"trace_id": self.report.trace_id, "report": self.report},
        )()

    def report_for(self, principal, trace_id):
        return self.report if trace_id == self.report.trace_id else None


def call(app, method, path, payload=b""):
    responses = []
    body = app(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": io.BytesIO(payload),
        },
        lambda status, headers: responses.append((status, headers)),
    )
    return responses[0], json.loads(b"".join(body))


def test_http_adapter_submits_goal_and_replays_report_without_client_identity():
    app = WsgiGovernedReadApplication(
        Control(),
        Resolver(Principal("user-1", "org-1", frozenset({"viewer"}))),
    )

    submitted, payload = call(
        app,
        "POST",
        "/api/workflows",
        json.dumps({"goal": "compare monthly revenue"}).encode(),
    )
    replayed, replay_payload = call(app, "GET", "/api/workflows/task-1")

    assert submitted[0] == "200 OK"
    assert payload["trace_id"] == "task-1"
    assert replayed[0] == "200 OK"
    assert replay_payload["report"]["trace_id"] == "task-1"


def test_http_adapter_rejects_malformed_goal_body():
    app = WsgiGovernedReadApplication(
        Control(),
        Resolver(Principal("user-1", "org-1", frozenset({"viewer"}))),
    )

    response, payload = call(app, "POST", "/api/workflows", b'{"goal":""}')

    assert response[0] == "400 Bad Request"
    assert payload["error"] == "Invalid request."
