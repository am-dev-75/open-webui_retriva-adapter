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

"""Tests for the FastAPI HTTP endpoints (T-22)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    """Set required env vars before importing the app."""
    monkeypatch.setenv("OWUI_BASE_URL", "http://owui-test:3000")
    monkeypatch.setenv("OWUI_API_KEY", "test-key")
    monkeypatch.setenv("RETRIVA_INGESTION_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_INGESTION_PORT", "8000")
    monkeypatch.setenv("RETRIVA_CHAT_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_CHAT_PORT", "8001")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api_test.db"))
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "9999")  # don't auto-poll


@pytest.fixture
async def api_client():
    """Create an async test client for the FastAPI app."""
    from adapter.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestHealthEndpoints:
    """Health and readiness probe tests."""

    async def test_healthz(self, api_client: AsyncClient) -> None:
        resp = await api_client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_readyz_structure(self, api_client: AsyncClient) -> None:
        # Upstreams are not reachable in test → not_ready is expected
        resp = await api_client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "checks" in body
        assert "owui" in body["checks"]
        assert "retriva" in body["checks"]


class TestMappingsEndpoint:
    """GET /api/v1/mappings tests."""

    async def test_empty_mappings(self, api_client: AsyncClient) -> None:
        resp = await api_client.get("/api/v1/mappings")
        assert resp.status_code == 200
        assert resp.json() == []


class TestMetricsEndpoint:
    """GET /metrics tests."""

    async def test_metrics_returns_prometheus_format(
        self, api_client: AsyncClient,
    ) -> None:
        resp = await api_client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        assert "adapter_files_synced_total" in text
        assert "adapter_files_deleted_total" in text
        assert "adapter_sync_errors_total" in text
        assert "adapter_poll_duration_seconds" in text