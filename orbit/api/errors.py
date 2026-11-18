"""Uniform JSON error envelopes and exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from orbit.api.middleware import current_request_id

_logger = logging.getLogger("orbit.api.errors")


def error_body(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    details: object = None,
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if request_id:
        error["request_id"] = request_id
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message, request_id=current_request_id()),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": ".".join(str(part) for part in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Request validation failed",
                request_id=current_request_id(),
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Never echo internals to clients; the full traceback stays in server logs.
        _logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error",
                "An unexpected error occurred.",
                request_id=current_request_id(),
            ),
        )
