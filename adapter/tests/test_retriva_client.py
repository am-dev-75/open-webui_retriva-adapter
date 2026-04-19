# SPDX-License-Identifier: MIT
"""Tests for adapter.retriva_client — format-aware routing."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from adapter.config import Settings
from adapter.models import FetchedFile
from adapter.pdf_extractor import PdfExtractionResult, PdfPage
from adapter.retriva_client import RetrivaClient


class TestRetrivaClientRouting:
    """RetrivaClient content-type routing tests."""

    @respx.mock
    async def test_ingest_text_routes_to_text_endpoint(
        self, settings: Settings,
    ) -> None:
        route = respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/text",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-1"},
            ),
        )

        fetched = FetchedFile(
            file_id="f-1", filename="notes.txt",
            content_type="text/plain", content=b"Hello world", size=11,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            doc_id = await rc.ingest(fetched)

        assert doc_id == "owui:f-1"
        assert route.called
        payload = route.calls[0].request
        assert b'"content_text"' in payload.content

    @respx.mock
    async def test_ingest_html_routes_to_html_endpoint(
        self, settings: Settings,
    ) -> None:
        route = respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/html",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-2"},
            ),
        )

        fetched = FetchedFile(
            file_id="f-2", filename="page.html",
            content_type="text/html", content=b"<h1>Hello</h1>", size=14,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            doc_id = await rc.ingest(fetched)

        assert doc_id == "owui:f-2"
        assert route.called
        payload = route.calls[0].request
        assert b'"html_content"' in payload.content

    async def test_ingest_unsupported_type_raises(
        self, settings: Settings,
    ) -> None:
        fetched = FetchedFile(
            file_id="f-3", filename="data.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=b"binary", size=6,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            with pytest.raises(ValueError, match="Unsupported content type"):
                await rc.ingest(fetched)

    @respx.mock
    async def test_ingest_content_type_with_charset(
        self, settings: Settings,
    ) -> None:
        """Content-Type with charset parameter should still route correctly."""
        route = respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/text",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok"},
            ),
        )

        fetched = FetchedFile(
            file_id="f-4", filename="readme.txt",
            content_type="text/plain; charset=utf-8",
            content=b"some text", size=9,
        )
        async with httpx.AsyncClient() as client:
            rc = RetrivaClient(settings, client)
            await rc.ingest(fetched)

        assert route.called


class TestRetrivaClientPdf:
    """RetrivaClient PDF ingestion tests."""

    @respx.mock
    async def test_ingest_pdf_sends_per_page_requests(
        self, settings: Settings,
    ) -> None:
        """Each PDF page should generate a separate POST to /api/v1/ingest/pdf."""
        extraction = PdfExtractionResult(
            title="Test Document",
            pages=[
                PdfPage(page_number=1, text="Page one content"),
                PdfPage(page_number=2, text="Page two content"),
            ],
            total_pages=3,
            skipped_pages=1,
        )

        route = respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/pdf",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-pdf"},
            ),
        )

        fetched = FetchedFile(
            file_id="f-pdf", filename="report.pdf",
            content_type="application/pdf",
            content=b"fake-pdf-bytes", size=14,
        )

        with patch("adapter.retriva_client.extract_pdf", return_value=extraction):
            async with httpx.AsyncClient() as client:
                rc = RetrivaClient(settings, client)
                doc_id = await rc.ingest(fetched)

        assert doc_id == "owui:f-pdf"
        # One request per page with text (2 pages)
        assert route.call_count == 2

    @respx.mock
    async def test_ingest_pdf_page_payload_format(
        self, settings: Settings,
    ) -> None:
        """Verify the JSON payload matches Retriva's PdfIngestRequest schema."""
        extraction = PdfExtractionResult(
            title="My Report",
            pages=[PdfPage(page_number=3, text="Third page text")],
            total_pages=5,
            skipped_pages=4,
        )

        route = respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/pdf",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-1"},
            ),
        )

        fetched = FetchedFile(
            file_id="f-5", filename="report.pdf",
            content_type="application/pdf",
            content=b"pdf-bytes", size=9,
        )

        with patch("adapter.retriva_client.extract_pdf", return_value=extraction):
            async with httpx.AsyncClient() as client:
                rc = RetrivaClient(settings, client)
                await rc.ingest(fetched)

        import json
        payload = json.loads(route.calls[0].request.content)
        assert payload["source_path"] == "owui:f-5"
        assert payload["page_title"] == "My Report"
        assert payload["content_text"] == "Third page text"
        assert payload["page_number"] == 3
        assert payload["total_pages"] == 5

    async def test_ingest_pdf_unreadable_raises(
        self, settings: Settings,
    ) -> None:
        """Unreadable PDFs should raise ValueError."""
        fetched = FetchedFile(
            file_id="f-bad", filename="corrupt.pdf",
            content_type="application/pdf",
            content=b"not-a-pdf", size=9,
        )

        with patch("adapter.retriva_client.extract_pdf", return_value=None):
            async with httpx.AsyncClient() as client:
                rc = RetrivaClient(settings, client)
                with pytest.raises(ValueError, match="Cannot extract text"):
                    await rc.ingest(fetched)

    @respx.mock
    async def test_ingest_pdf_server_error_raises(
        self, settings: Settings,
    ) -> None:
        """HTTP errors from Retriva should propagate."""
        extraction = PdfExtractionResult(
            title="Broken",
            pages=[PdfPage(page_number=1, text="text")],
            total_pages=1,
            skipped_pages=0,
        )

        respx.post(
            f"{settings.RETRIVA_BASE_URL}/api/v1/ingest/pdf",
        ).mock(
            return_value=httpx.Response(500, json={"detail": "internal error"}),
        )

        fetched = FetchedFile(
            file_id="f-err", filename="error.pdf",
            content_type="application/pdf",
            content=b"pdf", size=3,
        )

        with patch("adapter.retriva_client.extract_pdf", return_value=extraction):
            async with httpx.AsyncClient() as client:
                rc = RetrivaClient(settings, client)
                with pytest.raises(httpx.HTTPStatusError):
                    await rc.ingest(fetched)


class TestRetrivaClientDeleteHealth:
    """Delete and health check tests (unchanged behavior)."""

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
