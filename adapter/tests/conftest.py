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