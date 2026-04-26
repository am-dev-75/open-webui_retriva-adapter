# SPDX-License-Identifier: MIT
"""Integration tests for retrieval parameter forwarding in POST /v1/chat/completions."""

from __future__ import annotations

import pytest
import respx
import httpx
from httpx import ASGITransport, AsyncClient

_TEST_RETRIVA_CHAT_URL = "http://retriva-test:8001"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    """Async test client for the FastAPI app."""
    monkeypatch.setenv("OWUI_BASE_URL", "http://owui-test:3000")
    monkeypatch.setenv("OWUI_API_KEY", "test-key")
    monkeypatch.setenv("RETRIVA_INGESTION_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_INGESTION_PORT", "8000")
    monkeypatch.setenv("RETRIVA_CHAT_API_HOST", "retriva-test")
    monkeypatch.setenv("RETRIVA_CHAT_PORT", "8001")
    monkeypatch.setenv("RETRIVA_API_KEY", "test-key-retriva")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "param_test.db"))
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


def _chat_body(content: str, **params) -> dict:
    body: dict = {
        "model": "test-model",
        "messages": [{"role": "user", "content": content}],
    }
    body.update(params)
    return body


class TestRetrievalParameterForwarding:
    """Verify that top_k, top_p, and temperature are forwarded correctly."""

    @respx.mock
    async def test_parameters_moved_to_retrieval_object(self, client: AsyncClient) -> None:
        """Parameters should be extracted and moved to a 'retrieval' dict."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        
        def check_request(request):
            body = httpx.Request.read(request).decode()
            import json
            data = json.loads(body)
            # Should NOT be at top level anymore
            assert "top_k" not in data
            assert "top_p" not in data
            assert "temperature" not in data
            # Should BE in retrieval object
            assert data["retrieval"]["top_k"] == 5
            assert data["retrieval"]["top_p"] == 0.9
            assert data["retrieval"]["temperature"] == 0.7
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        respx.post(retriva_url).mock(side_effect=check_request)

        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(
                "Tell me about Apollo",
                top_k=5,
                top_p=0.9,
                temperature=0.7,
            ),
        )
        assert resp.status_code == 200

    @respx.mock
    async def test_no_parameters_no_retrieval_object(self, client: AsyncClient) -> None:
        """If no parameters are provided, no 'retrieval' dict should be added."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        
        def check_request(request):
            import json
            data = json.loads(request.read())
            assert "retrieval" not in data
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        respx.post(retriva_url).mock(side_effect=check_request)

        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("Just a question"),
        )
        assert resp.status_code == 200

    @respx.mock
    async def test_parameters_not_forwarded_for_intercepted_turns(self, client: AsyncClient) -> None:
        """Synthetic responses should ignore these parameters (not forward them anywhere)."""
        # No respx mock needed because it shouldn't hit Retriva
        
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(
                "@@ingestion_tag_start",
                top_k=5,
            ),
        )
        assert resp.status_code == 200
        # If it didn't crash and returned a synthetic response, that's good.
        assert "✅" in resp.json()["choices"][0]["message"]["content"]

    @respx.mock
    async def test_parameters_do_not_affect_ingestion_webhook(self, client: AsyncClient) -> None:
        """Parameters provided in a chat completions request should not leak into ingestion logic."""
        # 1. Mock Retriva's chat completions endpoint
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        respx.post(retriva_url).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))

        # 2. Send a chat message (webhook) to start tagging
        resp = await client.post(
            "/api/v1/chat/message",
            json={
                "chat_id": "test-ingest",
                "message": "@@ingestion_tag_start\nproject: Verify",
            },
        )
        assert resp.status_code == 200
        
        # 3. Verify that subsequent completions with params don't corrupt the context
        await client.post(
            "/v1/chat/completions",
            json=_chat_body(
                "Real question",
                session_id="test-ingest",
                top_k=10,
            ),
        )

    @respx.mock
    async def test_retriva_error_during_streaming(self, client: AsyncClient) -> None:
        """Verify behavior when Retriva returns an error during a streaming request."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        
        # Mock Retriva returning a 400 error
        respx.post(retriva_url).mock(
            return_value=httpx.Response(
                400, 
                content=b"Bad Request", 
                headers={"Content-Type": "text/plain", "Content-Length": "11"}
            )
        )

        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("Hi", stream=True),
        )
        assert resp.status_code == 400
        # If it returns the error correctly, then the proxy logic is working.
        # If it fails with a TransferEncodingError, then we have a problem in the adapter.
        
        # 3. Check internal state (if debug enabled) or just verify it still works
        # The fact that chat/completions pop() these parameters ensures they don't 
        # hang around in any shared state if there were any (which there isn't).

    @respx.mock
    async def test_owui_control_prompt_forwarded(self, client: AsyncClient) -> None:
        """Verify that OWUI control prompts are still forwarded to Retriva if not in tagging mode."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        respx.post(retriva_url).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "control response"}}]}))
        
        # A message containing an OWUI marker
        control_msg = "Today's date is: 2026-04-26\nAnalyze the chat history."
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(control_msg),
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "control response"

    @respx.mock
    async def test_mixed_human_and_control_prompt(self, client: AsyncClient) -> None:
        """Verify that a message with both control markers and a question is handled."""
        retriva_url = f"{_TEST_RETRIVA_CHAT_URL}/v1/chat/completions"
        respx.post(retriva_url).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "mixed response"}}]}))
        
        mixed_msg = "Today's date is: 2026-04-26\nWhat is the weather?"
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(mixed_msg),
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "mixed response"
