"""Unit tests for structured logging and secret redaction."""

from __future__ import annotations

import io
import json
import logging

from orbit.core.config import Settings
from orbit.core.logging import JsonFormatter, configure_logging, redact

# Built at runtime so the literal never looks like a live credential to scanners.
FAKE_OPENROUTER_KEY = "sk-" + "or-v1-" + "0123456789abcdef0123456789abcdef"
FAKE_BEARER = "Bearer " + "abcdefghijklmnop0123456789"


def test_redacts_openrouter_keys() -> None:
    masked = redact(f"calling provider with {FAKE_OPENROUTER_KEY}")
    assert FAKE_OPENROUTER_KEY not in masked
    assert "sk-or-v1-***" in masked


def test_redacts_authorization_header() -> None:
    masked = redact(f"Authorization: {FAKE_BEARER}")
    assert "abcdefghijklmnop0123456789" not in masked
    assert masked == "Authorization: ***"


def test_redacts_assignment_pairs() -> None:
    assert redact("api_key=super-secret-value") == "api_key=***"
    assert redact("password: hunter2") == "password: ***"
    assert redact("client_secret = topsecret") == "client_secret = ***"


def test_json_formatter_emits_structured_redacted_output() -> None:
    record = logging.LogRecord(
        name="orbit.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=%s",
        args=("abc123456789",),
        exc_info=None,
    )
    record.request_id = "req-1"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "info"
    assert payload["logger"] == "orbit.test"
    assert payload["request_id"] == "req-1"
    assert payload["message"] == "token=***"
    assert "abc123456789" not in json.dumps(payload)


def test_configure_logging_writes_redacted_lines(settings: Settings) -> None:
    stream = io.StringIO()
    configure_logging(settings, stream=stream)
    logging.getLogger("orbit.test").warning("provider key %s", FAKE_OPENROUTER_KEY)
    output = stream.getvalue()
    assert "WARNING" in output
    assert "sk-or-v1-***" in output
    assert FAKE_OPENROUTER_KEY not in output
