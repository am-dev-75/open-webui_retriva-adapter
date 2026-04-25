# SPDX-License-Identifier: MIT
"""Tests for adapter.config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapter.config import Settings, load_settings


class TestSettings:
    """Config validation tests (T-05)."""

    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OWUI_BASE_URL", "http://owui:3000")
        monkeypatch.setenv("OWUI_API_KEY", "key123")
        monkeypatch.setenv("RETRIVA_INGESTION_API_HOST", "retriva-ingest")
        monkeypatch.setenv("RETRIVA_INGESTION_PORT", "9000")
        monkeypatch.setenv("RETRIVA_CHAT_API_HOST", "retriva-chat")
        monkeypatch.setenv("RETRIVA_CHAT_PORT", "9001")

        s = load_settings()
        assert s.OWUI_BASE_URL == "http://owui:3000"
        assert s.OWUI_API_KEY == "key123"
        assert s.RETRIVA_API_PROTOCOL == "http"
        assert s.RETRIVA_INGESTION_API_HOST == "retriva-ingest"
        assert s.RETRIVA_INGESTION_PORT == 9000
        assert s.RETRIVA_CHAT_API_HOST == "retriva-chat"
        assert s.RETRIVA_CHAT_PORT == 9001
        assert s.POLL_INTERVAL_SECONDS == 30
        assert s.ADAPTER_PORT == 8500

    def test_computed_urls(self) -> None:
        s = Settings(
            OWUI_BASE_URL="http://x:1",
            OWUI_API_KEY="k",
            RETRIVA_API_PROTOCOL="https",
            RETRIVA_INGESTION_API_HOST="ingest.retriva.io",
            RETRIVA_INGESTION_PORT=443,
            RETRIVA_CHAT_API_HOST="chat.retriva.io",
            RETRIVA_CHAT_PORT=8443,
        )
        assert s.retriva_ingestion_url == "https://ingest.retriva.io:443"
        assert s.retriva_chat_url == "https://chat.retriva.io:8443"

    def test_defaults_for_retriva_fields(self) -> None:
        """Retriva fields all have defaults — only OWUI fields are required."""
        s = Settings(
            OWUI_BASE_URL="http://x:1",
            OWUI_API_KEY="k",
        )
        assert s.retriva_ingestion_url == "http://localhost:8000"
        assert s.retriva_chat_url == "http://localhost:8001"

    def test_missing_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear any env vars that might satisfy the requirement
        monkeypatch.delenv("OWUI_BASE_URL", raising=False)
        monkeypatch.delenv("OWUI_API_KEY", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            Settings()  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        missing_fields = {e["loc"][0] for e in errors}
        assert "OWUI_BASE_URL" in missing_fields
        assert "OWUI_API_KEY" in missing_fields

    def test_overrides_via_kwargs(self, tmp_path: Path) -> None:
        s = load_settings(
            OWUI_BASE_URL="http://x:1",
            OWUI_API_KEY="k",
            DB_PATH=tmp_path / "override.db",
            POLL_INTERVAL_SECONDS=10,
        )
        assert s.POLL_INTERVAL_SECONDS == 10
        assert s.DB_PATH == tmp_path / "override.db"

    def test_poll_interval_minimum(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                OWUI_BASE_URL="http://x:1",
                OWUI_API_KEY="k",
                POLL_INTERVAL_SECONDS=1,  # below ge=5
            )

