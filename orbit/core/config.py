"""Application settings and path resolution.

Settings are loaded from environment variables prefixed with ``ORBIT_`` and
optionally from a local ``.env`` file. Secrets are stored as ``SecretStr`` so
they never appear in reprs, logs, or serialized diagnostics.
"""

from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

APP_NAME = "ORBIT AI"
DEFAULT_PORT = 18700
SYSTEM_DATA_DIR = Path("/var/lib/orbit-ai")
SYSTEM_LOG_DIR = Path("/var/log/orbit-ai")

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _is_writable_dir(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _xdg_base(env_var: str, fallback: Path) -> Path:
    configured = os.environ.get(env_var)
    return Path(configured).expanduser() if configured else fallback


def platform_data_dir() -> Path:
    """Return the default per-user (or per-host) data directory."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows builds
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "ORBIT AI" if base else Path.home() / "AppData" / "Local" / "ORBIT AI"
    if _is_writable_dir(SYSTEM_DATA_DIR):
        return SYSTEM_DATA_DIR
    return _xdg_base("XDG_DATA_HOME", Path.home() / ".local" / "share") / "orbit-ai"


def platform_log_dir() -> Path:
    """Return the default log directory, falling back to the data directory."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows builds
        return platform_data_dir() / "logs"
    if _is_writable_dir(SYSTEM_LOG_DIR):
        return SYSTEM_LOG_DIR
    return platform_data_dir() / "logs"  # pragma: no cover - covered by unit tests


class Settings(BaseSettings):
    """Validated runtime configuration for ORBIT AI."""

    model_config = SettingsConfigDict(
        env_prefix="ORBIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
        validate_assignment=True,
    )

    env: Environment = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT

    data_dir: Path = Field(default_factory=platform_data_dir)
    log_dir: Path = Field(default_factory=platform_log_dir)
    database_url: str | None = None
    auto_migrate: bool = True

    log_level: LogLevel = "INFO"
    log_json: bool = False

    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Provider credentials. Empty until the user configures a provider.
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ollama_base_url: str = "http://127.0.0.1:11434"
    request_timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    @field_validator("port")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return value

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("host must not be empty")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("data_dir", "log_dir", mode="after")
    @classmethod
    def _normalize_path(cls, value: Path) -> Path:
        return value.expanduser().resolve(strict=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_path(self) -> Path:
        """Filesystem path of the SQLite database."""
        return self.data_dir / "orbit.db"

    @property
    def resolved_database_url(self) -> str:
        """Async SQLAlchemy URL; derived from ``data_dir`` unless overridden."""
        if self.database_url:
            return self.database_url
        return str(URL.create("sqlite+aiosqlite", database=str(self.database_path)))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def ensure_directories(self) -> None:
        """Create the data and log directories with restrictive permissions."""
        for directory in (self.data_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                with contextlib.suppress(PermissionError):
                    # Tighten pre-existing directories too (e.g. /var/lib/orbit-ai).
                    directory.chmod(0o700)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings; used by tests and the CLI after env changes."""
    get_settings.cache_clear()
