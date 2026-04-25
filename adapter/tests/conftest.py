# SPDX-License-Identifier: MIT
"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import pytest

from adapter.config import Settings
from adapter.mapping_store import MappingStore


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Create test settings with a temporary database path."""
    return Settings(
        OWUI_BASE_URL="http://test-owui:3000",
        OWUI_API_KEY="test-key-owui",
        RETRIVA_API_PROTOCOL="http",
        RETRIVA_INGESTION_API_HOST="test-retriva",
        RETRIVA_INGESTION_PORT=8000,
        RETRIVA_CHAT_API_HOST="test-retriva",
        RETRIVA_CHAT_PORT=8001,
        RETRIVA_API_KEY="test-key-retriva",
        DB_PATH=tmp_path / "test.db",
        POLL_INTERVAL_SECONDS=5,
        LOG_LEVEL="DEBUG",
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncGenerator[MappingStore, None]:
    """Create and open a temporary MappingStore."""
    s = MappingStore(tmp_path / "test.db")
    await s.open()
    yield s
    await s.close()
