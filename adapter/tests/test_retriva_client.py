# SPDX-License-Identifier: MIT
"""Tests for adapter.retriva_client."""

from __future__ import annotations

import httpx
import pytest
import respx

from adapter.config import Settings
from adapter.models import FetchedFile
from adapter.retriva_client import RetrivaClient


class TestRetrivaClient:
    """RetrivaClient tests (T-13)."""

    @respx.mock
    async def test_ingest_success(self, settings: Settings) -> None:
        respx.post(f"{settings.RETRIVA_BASE_URL}/api/v1/ingest").mock(
            return_value=httpx.Response(200, json={"doc_id": "d-42"}),
        )
        fetched = FetchedFile(
            file_id="f-1", filename="doc.pdf",
            content_type="application/pdf", content=b"data", size=4,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            doc_id = await rc.ingest(fetched)

        assert doc_id == "d-42"

    @respx.mock
    async def test_ingest_error_raises(self, settings: Settings) -> None:
        respx.post(f"{settings.RETRIVA_BASE_URL}/api/v1/ingest").mock(
            return_value=httpx.Response(422, json={"detail": "bad"}),
        )
        fetched = FetchedFile(
            file_id="f-1", filename="bad.pdf",
            content_type="application/pdf", content=b"x", size=1,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            with pytest.raises(httpx.HTTPStatusError):
                await rc.ingest(fetched)

    @respx.mock
    async def test_delete_success(self, settings: Settings) -> None:
        respx.delete(f"{settings.RETRIVA_BASE_URL}/api/v1/documents/d-1").mock(
            return_value=httpx.Response(200),
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            await rc.delete_document("d-1")  # should not raise

    @respx.mock
    async def test_health_ok(self, settings: Settings) -> None:
        respx.get(f"{settings.RETRIVA_BASE_URL}/healthz").mock(
            return_value=httpx.Response(200),
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            assert await rc.health() is True

    @respx.mock
    async def test_health_down(self, settings: Settings) -> None:
        respx.get(f"{settings.RETRIVA_BASE_URL}/healthz").mock(
            side_effect=httpx.ConnectError("refused"),
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            assert await rc.health() is False
