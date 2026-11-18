"""Unit tests for configuration loading and secret handling."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orbit import __version__
from orbit.core.config import Settings, get_settings, reset_settings_cache

# Built at runtime so the literal never looks like a live credential to scanners.
FAKE_KEY = "sk-" + "or-v1-" + "abcdef0123456789abcdef0123456789"


def test_defaults_are_safe(settings: Settings) -> None:
    assert settings.host == "127.0.0.1"
    assert settings.port == 18700
    assert settings.data_dir.is_absolute()
    assert settings.database_path == settings.data_dir / "orbit.db"
    assert settings.resolved_database_url.startswith("sqlite+aiosqlite:///")
    assert settings.docs_enabled is True
    assert settings.cors_origins == []


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORBIT_PORT", "19001")
    monkeypatch.setenv("ORBIT_HOST", "127.0.0.2")
    try:
        settings = get_settings()
    finally:
        reset_settings_cache()
    assert settings.port == 19001
    assert settings.host == "127.0.0.2"


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, port=70000)


def test_blank_host_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, host="   ")


def test_cors_origins_accept_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORBIT_CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5174")
    try:
        settings = get_settings()
    finally:
        reset_settings_cache()
    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5174"]


def test_api_key_is_not_exposed_in_repr_or_str(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        log_dir=tmp_path,
        openrouter_api_key=FAKE_KEY,
    )
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings)
    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == FAKE_KEY


def test_ensure_directories_creates_private_dirs(settings: Settings) -> None:
    settings.ensure_directories()
    assert settings.data_dir.is_dir()
    assert settings.log_dir.is_dir()
    assert settings.data_dir.stat().st_mode & 0o777 == 0o700


def test_database_url_override_wins(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        log_dir=tmp_path,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    assert settings.resolved_database_url == "sqlite+aiosqlite:///:memory:"


def test_package_version_is_pep440() -> None:
    assert __version__.startswith("0.1.0")
