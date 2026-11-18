"""Structured logging with secret redaction.

Log records are formatted as human-readable text or JSON. Every formatted line
passes through :func:`redact` so API keys and bearer tokens never reach disk or
stdout, even when a library logs them by accident.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

from orbit.core.config import Settings

REDACTED = "***"

_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenRouter and OpenAI-style keys.
    (re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{8,}"), f"sk-or-v1-{REDACTED}"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), f"sk-{REDACTED}"),
    # Authorization headers: mask everything after the scheme.
    (re.compile(r"(?i)\b(authorization)\s*[:=]\s*[^\r\n]+"), rf"\1: {REDACTED}"),
    (re.compile(r"(?i)\b(bearer)\s+\S+"), rf"\1 {REDACTED}"),
    # key=value / key: value pairs for common credential names.
    (
        re.compile(
            r"(?i)\b([\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password))"
            r"(\s*[=:]\s*)([^\s,;\"'&]+)"
        ),
        rf"\1\2{REDACTED}",
    ),
)

_EXTRA_FIELDS = (
    "request_id",
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


def redact(text: str) -> str:
    """Mask credential-looking substrings in ``text``."""
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _RedactingFormatter(logging.Formatter):
    """Base formatter that redacts the final rendered line."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class TextFormatter(_RedactingFormatter):
    default_format = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.default_format, datefmt="%Y-%m-%dT%H:%M:%S%z")


class JsonFormatter(_RedactingFormatter):
    """Emit one JSON object per line for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Let redaction run over the serialized payload so extra fields are covered too.
        return redact(json.dumps(payload, default=str, ensure_ascii=False))


def build_formatter(*, json_output: bool) -> logging.Formatter:
    return JsonFormatter() if json_output else TextFormatter()


def configure_logging(settings: Settings, stream: TextIO | None = None) -> None:
    """Install the ORBIT log handler on the root logger.

    Idempotent: only handlers created here are replaced, so third-party
    handlers (pytest's caplog, for example) keep working.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(build_formatter(json_output=settings.log_json))
    handler._orbit_handler = True  # type: ignore[attr-defined]

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_orbit_handler", False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Uvicorn installs its own handlers; route them through the ORBIT handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # Migration internals are only interesting when something goes wrong.
    logging.getLogger("alembic").setLevel(logging.WARNING)
