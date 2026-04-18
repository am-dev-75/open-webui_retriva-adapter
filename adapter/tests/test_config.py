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
        monkeypatch.setenv("RETRIVA_BASE_URL", "http://retriva:8400")

        s = load_settings()
        assert s.OWUI_BASE_URL == "http://owui:3000"
        assert s.OWUI_API_KEY == "key123"
        assert s.RETRIVA_BASE_URL == "http://retriva:8400"
        assert s.POLL_INTERVAL_SECONDS == 30
        assert s.ADAPTER_PORT == 8500

    def test_missing_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear any env vars that might satisfy the requirement
        monkeypatch.delenv("OWUI_BASE_URL", raising=False)
        monkeypatch.delenv("OWUI_API_KEY", raising=False)
        monkeypatch.delenv("RETRIVA_BASE_URL", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            Settings()  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        missing_fields = {e["loc"][0] for e in errors}
        assert "OWUI_BASE_URL" in missing_fields
        assert "OWUI_API_KEY" in missing_fields
        assert "RETRIVA_BASE_URL" in missing_fields

    def test_overrides_via_kwargs(self, tmp_path: Path) -> None:
        s = load_settings(
            OWUI_BASE_URL="http://x:1",
            OWUI_API_KEY="k",
            RETRIVA_BASE_URL="http://y:2",
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
                RETRIVA_BASE_URL="http://y:2",
                POLL_INTERVAL_SECONDS=1,  # below ge=5
            )
