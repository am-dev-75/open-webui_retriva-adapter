# SPDX-License-Identifier: MIT
"""Environment-driven configuration for the adapter."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.1"


class Settings(BaseSettings):
    """Adapter settings loaded from environment variables.

    Required:
        OWUI_BASE_URL  – Open WebUI base URL (e.g. http://openwebui:3000)
        OWUI_API_KEY   – Bearer token for the OWUI API
        RETRIVA_BASE_URL – Retriva base URL (e.g. http://retriva:8400)

    Optional (with defaults):
        RETRIVA_API_KEY, POLL_INTERVAL_SECONDS, DB_PATH,
        LOG_LEVEL, ADAPTER_PORT
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=True,
    )

    # --- Required -----------------------------------------------------------
    OWUI_BASE_URL: str = Field(
        ...,
        description="Open WebUI base URL (e.g. http://openwebui:3000)",
    )
    OWUI_API_KEY: str = Field(
        ...,
        description="Bearer token for the Open WebUI API",
    )
    RETRIVA_BASE_URL: str = Field(
        ...,
        description="Retriva base URL (e.g. http://retriva:8400)",
    )

    # --- Optional ------------------------------------------------------------
    RETRIVA_API_KEY: str = Field(
        default="",
        description="Optional Retriva auth token",
    )
    LLM_UPSTREAM_URL: str = Field(
        default="",
        description="Base URL of the upstream LLM API for proxied requests "
        "(e.g. http://ollama:11434/v1). Required for chat completions proxy.",
    )
    LLM_API_KEY: str = Field(
        default="",
        description="Service credential (Bearer token) for the upstream LLM API. "
        "Separate from inbound auth — the adapter enforces least privilege.",
    )
    POLL_INTERVAL_SECONDS: int = Field(
        default=30,
        ge=5,
        description="Seconds between polling cycles",
    )
    DB_PATH: Path = Field(
        default=Path("./data/adapter.db"),
        description="SQLite database path for mappings",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level",
    )
    ADAPTER_PORT: int = Field(
        default=8500,
        ge=1,
        le=65535,
        description="HTTP port for health/metrics/API",
    )

    # --- Retry tuning --------------------------------------------------------
    MAX_RETRIES: int = Field(default=3, ge=0)
    BACKOFF_BASE_SECONDS: float = Field(default=1.0, gt=0)
    BACKOFF_MAX_SECONDS: float = Field(default=30.0, gt=0)
    HTTP_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)


def load_settings(**overrides: object) -> Settings:
    """Create a validated ``Settings`` instance.

    Keyword arguments override environment variables – useful in tests.
    """
    return Settings(**overrides)  # type: ignore[arg-type]
