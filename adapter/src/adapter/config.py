# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Environment-driven configuration for the adapter."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.2.2"


class Settings(BaseSettings):
    """Adapter settings loaded from environment variables.

    Required:
        OWUI_BASE_URL  – Open WebUI base URL (e.g. http://openwebui:3000)
        OWUI_API_KEY   – Bearer token for the OWUI API

    Retriva connection (with defaults):
        RETRIVA_API_PROTOCOL      – http or https (default: http)
        RETRIVA_INGESTION_API_HOST – host for the ingestion API (default: localhost)
        RETRIVA_INGESTION_PORT     – port for the ingestion API (default: 8000)
        RETRIVA_CHAT_API_HOST      – host for the chat API (default: localhost)
        RETRIVA_CHAT_PORT          – port for the chat API (default: 8001)

    Optional (with defaults):
        RETRIVA_API_KEY, POLL_INTERVAL_SECONDS, DB_PATH,
        LOG_LEVEL, ADAPTER_PORT
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=True,
        populate_by_name=True,
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

    # --- Retriva connection --------------------------------------------------
    RETRIVA_API_PROTOCOL: str = Field(
        default="http",
        description="Protocol for Retriva APIs (http or https)",
    )
    RETRIVA_INGESTION_API_HOST: str = Field(
        default="localhost",
        description="Hostname for the Retriva ingestion API",
    )
    RETRIVA_INGESTION_PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port for the Retriva ingestion API",
    )
    RETRIVA_CHAT_API_HOST: str = Field(
        default="localhost",
        description="Hostname for the Retriva chat API",
    )
    RETRIVA_CHAT_PORT: int = Field(
        default=8001,
        ge=1,
        le=65535,
        description="Port for the Retriva chat API",
    )

    # --- Optional ------------------------------------------------------------
    RETRIVA_API_KEY: str = Field(
        default="",
        description="Optional Retriva auth token",
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

    # --- Metadata / KB --------------------------------------------------------
    DEFAULT_KB_ID: str = Field(
        default="",
        description="Default Knowledge Base ID when none provided in webhook",
    )
    ENABLE_DEBUG_ENDPOINTS: bool = Field(
        default=False,
        description="Enable /internal/* debug endpoints (set THIN_ADAPTER_DEBUG_ENDPOINTS=true)",
        validation_alias="THIN_ADAPTER_DEBUG_ENDPOINTS",
    )

    # --- Chat polling (directive observation) --------------------------------
    CHAT_POLL_ENABLED: bool = Field(
        default=True,
        description="Enable chat message polling for directive detection",
    )
    CHAT_POLL_INTERVAL_SECONDS: int = Field(
        default=5,
        ge=1,
        description="Seconds between chat message polling cycles (directive responsiveness)",
    )

    # --- Retry tuning --------------------------------------------------------
    MAX_RETRIES: int = Field(default=3, ge=0)
    BACKOFF_BASE_SECONDS: float = Field(default=1.0, gt=0)
    BACKOFF_MAX_SECONDS: float = Field(default=30.0, gt=0)
    HTTP_TIMEOUT_SECONDS: float = Field(default=300.0, gt=0)

    # --- Computed URLs -------------------------------------------------------

    @property
    def retriva_ingestion_url(self) -> str:
        """Full base URL for the Retriva ingestion API."""
        return (
            f"{self.RETRIVA_API_PROTOCOL}://"
            f"{self.RETRIVA_INGESTION_API_HOST}:{self.RETRIVA_INGESTION_PORT}"
        )

    @property
    def retriva_chat_url(self) -> str:
        """Full base URL for the Retriva chat API."""
        return (
            f"{self.RETRIVA_API_PROTOCOL}://"
            f"{self.RETRIVA_CHAT_API_HOST}:{self.RETRIVA_CHAT_PORT}"
        )


def load_settings(**overrides: object) -> Settings:
    """Create a validated ``Settings`` instance.

    Keyword arguments override environment variables – useful in tests.
    """
    return Settings(**overrides)  # type: ignore[arg-type]
