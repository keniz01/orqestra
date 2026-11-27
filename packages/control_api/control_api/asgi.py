"""ASGI transport for the governed read control boundary."""

from __future__ import annotations

import io
import json
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .http import PrincipalResolver, WsgiGovernedReadApplication
from .service import GovernedReadControl

ASGIMessage = dict[str, Any]
Send = Callable[[ASGIMessage], Awaitable[None]]
Receive = Callable[[], Awaitable[ASGIMessage]]
ReadinessCheck = Callable[[], bool]


class AsgiGovernedReadApplication:
    """Expose health endpoints and bridge HTTP requests to the WSGI boundary."""

    def __init__(
        self,
        control: GovernedReadControl,
        principal_resolver: PrincipalResolver,
        *,
        readiness_check: ReadinessCheck | None = None,
    ) -> None:
        self._wsgi = WsgiGovernedReadApplication(control, principal_resolver)
        self._readiness_check = readiness_check or (lambda: True)

    async def __call__(
        self, scope: dict[str, Any], receive: Receive, send: Send
    ) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type != "http":
            await self._send_json(send, 404, {"error": "Not found."})
            return

        path = str(scope.get("path", ""))
        if path == "/healthz":
            await self._send_json(send, 200, {"status": "ok"})
            return
        if path == "/readyz":
            ready = self._readiness_check()
            await self._send_json(
                send,
                200 if ready else 503,
                {"status": "ready" if ready else "not_ready"},
            )
            return

        try:
            environ = await _as_wsgi_environ(scope, receive)
            response_status: str | None = None
            response_headers: list[tuple[str, str]] = []

            def start_response(
                status: str, headers: list[tuple[str, str]]
            ) -> None:
                nonlocal response_status, response_headers
                response_status = status
                response_headers = headers

            body = b"".join(
                await asyncio.to_thread(self._wsgi, environ, start_response)
            )
            if response_status is None:
                raise RuntimeError("WSGI application did not set a response status.")
            status_code = int(response_status.split(" ", 1)[0])
        except ValueError:
            await self._send_json(send, 400, {"error": "Invalid request."})
            return
        except Exception:
            await self._send_json(send, 500, {"error": "Request failed."})
            return

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in response_headers
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    async def _send_json(send: Send, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


async def _as_wsgi_environ(
    scope: dict[str, Any], receive: Receive
) -> dict[str, object]:
    body = bytearray()
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            raise ValueError("Invalid request stream.")
        chunk = message.get("body", b"")
        if not isinstance(chunk, bytes):
            raise ValueError("Invalid request body.")
        body.extend(chunk)
        if len(body) > 16_384:
            raise ValueError("Request body is too large.")
        if not message.get("more_body", False):
            break

    environ: dict[str, object] = {
        "REQUEST_METHOD": str(scope.get("method", "GET")),
        "PATH_INFO": str(scope.get("path", "")),
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    for name, value in scope.get("headers", []):
        header_name = name.decode("latin-1").upper().replace("-", "_")
        decoded = value.decode("latin-1")
        if header_name == "CONTENT_LENGTH":
            environ["CONTENT_LENGTH"] = decoded
        elif header_name == "CONTENT_TYPE":
            environ["CONTENT_TYPE"] = decoded
        else:
            environ[f"HTTP_{header_name}"] = decoded
    return environ
