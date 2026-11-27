"""Small WSGI adapter for the transport-neutral governed read boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from typing import Protocol

from execution_kernel import Principal

from .service import GovernedReadControl, GoalRequest

_LOGGER = logging.getLogger(__name__)


class PrincipalResolver(Protocol):
    """Resolve a trusted principal from an authenticated request."""

    def resolve(self, environ: dict[str, object]) -> Principal:
        """Return the server-validated principal or raise PermissionError."""


class WsgiGovernedReadApplication:
    """Expose goal submission and report replay without trusting request headers."""

    def __init__(
        self,
        control: GovernedReadControl,
        principal_resolver: PrincipalResolver,
    ) -> None:
        self._control = control
        self._principal_resolver = principal_resolver

    def __call__(
        self,
        environ: dict[str, object],
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        try:
            principal = self._principal_resolver.resolve(environ)
        except PermissionError as exc:
            _LOGGER.info("Request authentication failed: %s", exc)
            return self._response(
                start_response, "401 Unauthorized", {"error": "Authentication required."}
            )

        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", ""))
        if method == "POST" and path == "/api/workflows":
            return self._submit(environ, principal, start_response)
        if method == "GET" and path.startswith("/api/workflows/"):
            trace_id = path.removeprefix("/api/workflows/")
            try:
                report = self._control.report_for(principal, trace_id)
            except (PermissionError, ValueError) as exc:
                _LOGGER.info("Report request rejected: %s", exc)
                return self._response(
                    start_response, "404 Not Found", {"error": "Report not found."}
                )
            if report is None:
                return self._response(
                    start_response, "404 Not Found", {"error": "Report not found."}
                )
            return self._response(start_response, "200 OK", {"report": _report_json(report)})
        return self._response(start_response, "404 Not Found", {"error": "Not found."})

    def _submit(
        self,
        environ: dict[str, object],
        principal: Principal,
        start_response: Callable[[str, list[tuple[str, str]]], object],
    ) -> Iterable[bytes]:
        try:
            body = _read_json(environ)
            response = self._control.submit(principal, GoalRequest(body["goal"]))
        except PermissionError as exc:
            _LOGGER.info("Workflow request rejected: %s", exc)
            return self._response(
                start_response, "403 Forbidden", {"error": "Request not authorized."}
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _LOGGER.info("Invalid workflow request: %s", exc)
            return self._response(
                start_response, "400 Bad Request", {"error": "Invalid request."}
            )
        except Exception:
            _LOGGER.exception("Unhandled workflow request failure")
            return self._response(
                start_response, "500 Internal Server Error", {"error": "Request failed."}
            )
        return self._response(
            start_response,
            "200 OK",
            {"trace_id": response.trace_id, "report": _report_json(response.report)},
        )

    @staticmethod
    def _response(
        start_response: Callable[[str, list[tuple[str, str]]], object],
        status: str,
        payload: dict[str, object],
    ) -> Iterable[bytes]:
        body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]


def _read_json(environ: dict[str, object]) -> dict[str, object]:
    try:
        length = int(str(environ.get("CONTENT_LENGTH", "0")))
    except ValueError as exc:
        raise ValueError("Content-Length must be an integer.") from exc
    if length < 1 or length > 16_384:
        raise ValueError("Request body must be between 1 and 16384 bytes.")
    stream = environ.get("wsgi.input")
    if stream is None or not hasattr(stream, "read"):
        raise ValueError("Request body is missing.")
    raw = stream.read(length)
    if not isinstance(raw, bytes):
        raise ValueError("Request body is invalid.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object.")
    return value


def _report_json(report: object) -> dict[str, object]:
    return {
        "goal": report.goal,
        "state": report.state.value,
        "values": dict(report.values),
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
