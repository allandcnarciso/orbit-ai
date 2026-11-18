"""Request correlation middleware.

Pure ASGI (not BaseHTTPMiddleware) so streaming responses are not buffered and
context variables propagate correctly to Server-Sent Events.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"

request_id_var: ContextVar[str] = ContextVar("orbit_request_id", default="")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_logger = logging.getLogger("orbit.api.request")


def current_request_id() -> str:
    return request_id_var.get()


class RequestContextMiddleware:
    """Assign a request id, emit one access log line and time the request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.decode("latin-1").lower() == REQUEST_ID_HEADER.lower():
                incoming = raw_value.decode("latin-1").strip()
                break
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex

        request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.append(REQUEST_ID_HEADER, request_id)
                headers.append(PROCESS_TIME_HEADER, f"{(time.perf_counter() - started) * 1000:.1f}")
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            _logger.info(
                "%s %s -> %s",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code,
                extra={
                    "request_id": request_id,
                    "method": scope.get("method", "-"),
                    "path": scope.get("path", "-"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.set("")
