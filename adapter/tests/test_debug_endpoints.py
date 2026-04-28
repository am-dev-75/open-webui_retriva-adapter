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

"""Tests for debug mapping endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from adapter.main import _register_debug_endpoints


@pytest.fixture
def debug_app() -> FastAPI:
    """Create a standalone FastAPI app with debug endpoints registered."""
    app = FastAPI()
    _register_debug_endpoints(app)
    return app


@pytest.fixture
async def debug_client(debug_app: FastAPI) -> AsyncClient:
    """Create an async test client for the debug app."""
    transport = ASGITransport(app=debug_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestDebugMappingEndpoints:
    
    async def test_knowledge_bases_endpoint(self, debug_client: AsyncClient) -> None:
        """Test that the KB mapping endpoint returns a list (empty if store uninitialized)."""
        resp = await debug_client.get("/internal/mappings/knowledge-bases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_documents_endpoint_empty(self, debug_client: AsyncClient) -> None:
        """Test document mappings endpoint when store is not initialized or empty."""
        # _store in main.py is initialized during the lifespan event. 
        # In this standalone app, it might be None or empty.
        # But wait, _store is a module-level variable in adapter.main.
        # Let's mock it or just verify it returns a list (empty if uninitialized).
        resp = await debug_client.get("/internal/mappings/documents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_document_lookup_not_found(self, debug_client: AsyncClient) -> None:
        """Test single document lookup for a non-existent file ID."""
        resp = await debug_client.get("/internal/mappings/documents/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json()["detail"] in ("Mapping not found", "Store not initialized")


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    """Set required env vars before importing the app."""
    monkeypatch.setenv("OWUI_BASE_URL", "http://owui-test:3000")
    monkeypatch.setenv("OWUI_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api_test.db"))
    # Do NOT set THIN_ADAPTER_DEBUG_ENDPOINTS, so it defaults to False


@pytest.fixture
async def api_client():
    """Create an async test client for the FastAPI app."""
    # We must import after env vars are patched
    from adapter.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestMainAppGating:
    
    async def test_endpoints_disabled_by_default(self, api_client: AsyncClient) -> None:
        """Test that the main app does not have the endpoints by default."""
        resp = await api_client.get("/internal/mappings/knowledge-bases")
        assert resp.status_code == 404