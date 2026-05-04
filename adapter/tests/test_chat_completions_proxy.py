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

"""Integration tests for POST /v1/chat/completions — UX-aware routing."""

from __future__ import annotations

import pytest
import respx
import httpx
from httpx import ASGITransport, AsyncClient

# Retriva chat URL used in test fixtures — built from the env vars below
_TEST_RETRIVA_CHAT_URL = "http://retriva-test:8001"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    """Async test client for the FastAPI app. Manually initializes globals."""
    monkeypatch.setenv("OWUI_BASE_URL", "http://owui-test:3000")
    monkeypatch.setenv("OWUI_API_KEY", "test-key")
    monkeypatch.setenv("RETRIVA_INGESTION_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_INGESTION_PORT", "8000")
    monkeypatch.setenv("RETRIVA_CHAT_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_CHAT_PORT", "8001")
    monkeypatch.setenv("RETRIVA_API_KEY", "test-key-retriva")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "proxy_test.db"))
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "9999")

    import adapter.main as _main
    from adapter.config import Settings
    from adapter.ingestion_context import IngestionContext
    
    _main._settings = Settings()
    _main._http_client = httpx.AsyncClient()
    _main._ingestion_ctx = IngestionContext()

    from adapter.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _chat_body(content: str, *, session_id: str | None = None) -> dict:
    body: dict = {
        "model": "test-model",
        "messages": [{"role": "user", "content": content}],
    }
    if session_id is not None:
        body["session_id"] = session_id
    return body


class TestDirectiveInterception:
    """Directive-only turns must NOT be forwarded to Retriva."""

    async def test_tag_start_returns_synthetic_ack(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("@@ingestion_tag_start\nproject: Apollo"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["finish_reason"] == "stop"
        content = body["choices"][0]["message"]["content"]
        assert "✅" in content
        assert "Apollo" in content

    async def test_tag_stop_returns_synthetic_ack(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("@@ingestion_tag_stop"),
        )
        assert resp.status_code == 200
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        assert "🛑" in content


class TestUploadInterception:
    """Upload-only turns must NOT be forwarded to Retriva."""

    async def test_upload_only_returns_synthetic_ack(self, client: AsyncClient) -> None:
        # First, activate the ingestion context for this session
        await client.post("/v1/chat/completions", json=_chat_body("@@ingestion_tag_start", session_id="test-session"))
        
        # Now send an empty message
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("", session_id="test-session"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "✅ Document received" in body["choices"][0]["message"]["content"]


class TestCombinedInterception:
    """Directive + files, no question → combined ack."""

    async def test_directive_plus_upload_ack(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(
                "@@ingestion_tag_start\nproject: Beta",
                session_id="test-session-2",
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        assert "✅ Document received" in content
        assert "project" in content


class TestForwardRouting:
    """Substantive questions must be forwarded to Retriva (not the LLM)."""

    @respx.mock
    async def test_question_proxied_to_retriva(self, client: AsyncClient) -> None:
        """Real question is forwarded to Retriva's chat/completions endpoint."""
        # Mock Retriva's chat completions endpoint
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        retriva_response = {
            "id": "chatcmpl-retriva-123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "retriva-rag",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "The project is on track.",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        }
        respx.post(retriva_url).mock(
            return_value=httpx.Response(200, json=retriva_response),
        )

        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("What is the project status?"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "chatcmpl-retriva-123"
        assert body["choices"][0]["message"]["content"] == "The project is on track."

    @respx.mock
    async def test_question_propagates_chat_context(self, client: AsyncClient) -> None:
        """Forwarded question must include kb_ids and user_metadata_filter if active."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        
        # 1. Set up context by sending a directive
        await client.post(
            "/v1/chat/completions",
            json=_chat_body("@@ingestion_tag_start\nproject: Alpha", session_id="context-session"),
        )
        
        # 2. Mock Retriva to capture and verify the body
        def capture_request(request):
            import json
            payload = json.loads(request.content)
            # Verify the injected filter
            if payload.get("user_metadata_filter") == {"project": "Alpha"}:
                return httpx.Response(
                    200, 
                    json={
                        "id": "cmpl-123",
                        "object": "chat.completion",
                        "choices": [{"message": {"content": "Metadata received"}, "finish_reason": "stop"}]
                    }
                )
            return httpx.Response(400, json={"error": "Filter missing or wrong"})

        respx.post(retriva_url).mock(side_effect=capture_request)

        # 3. Send a question
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("Tell me about the project.", session_id="context-session"),
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Metadata received"


class TestModelsProxy:
    """GET /v1/models must proxy Retriva's model list."""

    @respx.mock
    async def test_models_proxied_to_retriva(self, client: AsyncClient) -> None:
        """Model list is fetched from Retriva's chat API."""
        import adapter.main as _main
        from adapter.config import Settings

        _main._settings = Settings(
            OWUI_BASE_URL="http://owui-test:3000",
            OWUI_API_KEY="test-key",
            RETRIVA_CHAT_API_HOST="retriva-test",
            RETRIVA_CHAT_PORT=8001,
            RETRIVA_API_KEY="test-key-retriva",
        )
        _main._http_client = httpx.AsyncClient()

        try:
            retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/models"
            models_response = {
                "object": "list",
                "data": [
                    {"id": "retriva-rag", "object": "model", "owned_by": "retriva"},
                ],
            }
            respx.get(retriva_url).mock(
                return_value=httpx.Response(200, json=models_response),
            )

            resp = await client.get("/v1/models")
            assert resp.status_code == 200
            body = resp.json()
            assert body["object"] == "list"
            assert len(body["data"]) == 1
            assert body["data"][0]["id"] == "retriva-rag"
        finally:
            if _main._http_client:
                await _main._http_client.aclose()
            _main._settings = None
            _main._http_client = None

    async def test_models_returns_503_when_not_initialized(self, client: AsyncClient) -> None:
        """Before lifespan, returns empty list with 503."""
        import adapter.main as _main

        # Ensure settings are None (no lifespan)
        orig_settings = _main._settings
        _main._settings = None
        try:
            resp = await client.get("/v1/models")
            assert resp.status_code == 503
            body = resp.json()
            assert body["object"] == "list"
            assert body["data"] == []
        finally:
            _main._settings = orig_settings


class TestRegressionExistingEndpoints:
    """Existing endpoints must continue to work."""

    async def test_healthz(self, client: AsyncClient) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

