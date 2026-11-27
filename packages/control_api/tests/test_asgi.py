from __future__ import annotations

import asyncio
import json

from control_api import AsgiGovernedReadApplication
from execution_kernel import Principal


class Resolver:
    def resolve(self, environ):
        return Principal("user-1", "org-1", frozenset({"viewer"}))


class Control:
    def submit(self, principal, request):
        raise AssertionError("health endpoint must not invoke control")

    def report_for(self, principal, trace_id):
        return None


def call(app, scope, messages):
    received = iter(messages)
    sent = []

    async def receive():
        return next(received)

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def test_asgi_health_endpoint_is_unauthenticated():
    sent = call(
        AsgiGovernedReadApplication(Control(), Resolver()),
        {"type": "http", "path": "/healthz", "method": "GET", "headers": []},
        [],
    )

    assert sent[0]["status"] == 200
    assert json.loads(sent[1]["body"]) == {"status": "ok"}


def test_asgi_readiness_endpoint_returns_service_unavailable_when_not_ready():
    sent = call(
        AsgiGovernedReadApplication(
            Control(), Resolver(), readiness_check=lambda: False
        ),
        {"type": "http", "path": "/readyz", "method": "GET", "headers": []},
        [],
    )

    assert sent[0]["status"] == 503
    assert json.loads(sent[1]["body"]) == {"status": "not_ready"}


def test_asgi_bridges_authenticated_request_to_wsgi_boundary():
    sent = call(
        AsgiGovernedReadApplication(Control(), Resolver()),
        {"type": "http", "path": "/api/workflows/nope", "method": "GET", "headers": []},
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert sent[0]["status"] == 404
    assert json.loads(sent[1]["body"]) == {"error": "Report not found."}
