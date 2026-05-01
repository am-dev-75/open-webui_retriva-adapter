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

"""Tests for the system events webhook endpoint (/api/v1/events)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pathlib import Path

from adapter.main import app
from adapter.config import Settings
import adapter.main as main_mod


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_INGESTION_API_HOST="retriva",
        RETRIVA_INGESTION_PORT=8400,
        DB_PATH=tmp_path / "events.db",
        POLL_INTERVAL_SECONDS=3600,
    )


@pytest.fixture
def client(test_settings, monkeypatch):
    """Create a TestClient with mocked dependencies."""
    # We need to manually set the globals in main_mod because lifespan
    # might not run or might use different settings in tests.
    monkeypatch.setattr(main_mod, "_settings", test_settings)
    
    # We don't want to actually start the scheduler or open real DBs here
    # if we can avoid it, but for a simple endpoint test we can mock the orchestrator.
    class MockOrchestrator:
        def __init__(self):
            self.ingested_files = []
            self.deleted_files = []

        async def ingest_with_context(self, file_ids, chat_id):
            self.ingested_files.extend(file_ids)
            from adapter.models import SyncResult
            return SyncResult(ingested=len(file_ids))

        async def delete_by_file_id(self, file_id):
            self.deleted_files.append(file_id)
            return True

    mock_orch = MockOrchestrator()
    monkeypatch.setattr(main_mod, "_orchestrator", mock_orch)
    
    return TestClient(app), mock_orch


class TestSystemEvents:
    """Tests for the /api/v1/events endpoint."""

    def test_knowledge_added_triggers_ingestion(self, client):
        tc, mock_orch = client
        
        response = tc.post(
            "/api/v1/events",
            json={
                "event": "knowledge.document.added",
                "data": {"id": "f-123", "filename": "test.pdf"}
            }
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "ingestion_triggered"
        assert "f-123" in mock_orch.ingested_files

    def test_file_created_triggers_ingestion(self, client):
        tc, mock_orch = client
        
        response = tc.post(
            "/api/v1/events",
            json={
                "event": "file.created",
                "data": {"id": "f-456"}
            }
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "ingestion_triggered"
        assert "f-456" in mock_orch.ingested_files

    def test_knowledge_deleted_triggers_deletion(self, client):
        tc, mock_orch = client
        
        response = tc.post(
            "/api/v1/events",
            json={
                "event": "knowledge.document.deleted",
                "data": {"id": "f-789"}
            }
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "deletion_processed"
        assert response.json()["success"] is True
        assert "f-789" in mock_orch.deleted_files

    def test_unknown_event_is_ignored(self, client):
        tc, mock_orch = client
        
        response = tc.post(
            "/api/v1/events",
            json={
                "event": "user.signup",
                "data": {"id": "user-1"}
            }
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert len(mock_orch.ingested_files) == 0
        assert len(mock_orch.deleted_files) == 0

    def test_invalid_json_returns_400(self, client):
        tc, _ = client
        
        response = tc.post(
            "/api/v1/events",
            content="not json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 400
