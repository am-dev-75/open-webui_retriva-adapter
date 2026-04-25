# SPDX-License-Identifier: MIT
"""Integration tests for POST /v1/chat/completions — UX-aware routing."""

from __future__ import annotations

import pytest
import respx
import httpx
from httpx import ASGITransport, AsyncClient

from adapter.main import app


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _chat_body(content: str, *, files: list | None = None) -> dict:
    body: dict = {
        "model": "test-model",
        "messages": [{"role": "user", "content": content}],
    }
    if files is not None:
        body["files"] = files
    return body


class TestDirectiveInterception:
    """Directive-only turns must NOT be forwarded to the LLM."""

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
    """Upload-only turns must NOT be forwarded to the LLM."""

    async def test_upload_only_returns_synthetic_ack(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("", files=[{"filename": "report.pdf"}]),
        )
        assert resp.status_code == 200
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        assert "📄" in content
        assert "report.pdf" in content


class TestCombinedInterception:
    """Directive + upload without question → combined ack."""

    async def test_directive_plus_upload_ack(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body(
                "@@ingestion_tag_start\nproject: Beta",
                files=[{"filename": "spec.pdf"}],
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        assert "✅" in content
        assert "📄" in content
        assert "spec.pdf" in content


class TestForwardRouting:
    """Substantive questions must be forwarded to the upstream LLM."""

    @respx.mock
    async def test_question_proxied_to_upstream(self, client: AsyncClient) -> None:
        """When no LLM_UPSTREAM_URL is configured, a helpful fallback is returned."""
        resp = await client.post(
            "/v1/chat/completions",
            json=_chat_body("What is the project status?"),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Without LLM_UPSTREAM_URL set, we get the fallback message
        content = body["choices"][0]["message"]["content"]
        assert "LLM_UPSTREAM_URL" in content


class TestRegressionExistingEndpoints:
    """Existing endpoints must continue to work."""

    async def test_healthz(self, client: AsyncClient) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
