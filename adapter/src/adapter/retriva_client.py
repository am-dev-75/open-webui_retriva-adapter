# SPDX-License-Identifier: MIT
"""Retriva API client — forwards files for ingestion and propagates deletions.

Routes files to the correct format-specific Retriva endpoint based on
content type. For PDFs, text is extracted page-by-page and submitted
individually to ``/api/v1/ingest/pdf``.
"""

from __future__ import annotations

import uuid

import httpx

from adapter.config import Settings
from adapter.models import FetchedFile
from adapter.pdf_extractor import extract_pdf

from adapter.logger import get_logger

logger = get_logger(__name__)

# Content types we know how to route
_PDF_TYPES = {"application/pdf"}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {"text/plain", "text/markdown", "text/csv"}


class RetrivaClient:
    """HTTP client for Retriva ingestion and document management."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.RETRIVA_BASE_URL.rstrip("/")
        self._api_key = settings.RETRIVA_API_KEY
        self._client = client

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def ingest(self, fetched: FetchedFile) -> str:
        """Forward a file to Retriva for ingestion.

        Routes to the correct format-specific endpoint based on content type.
        Returns a synthetic ``doc_id`` for mapping purposes.
        Raises on HTTP errors.
        """
        content_type = (fetched.content_type or "").split(";")[0].strip().lower()

        if content_type in _PDF_TYPES:
            return await self._ingest_pdf(fetched)
        elif content_type in _HTML_TYPES:
            return await self._ingest_html(fetched)
        elif content_type in _TEXT_TYPES:
            return await self._ingest_text(fetched)
        else:
            raise ValueError(
                f"Unsupported content type '{content_type}' for file "
                f"'{fetched.filename}'. Supported types: PDF, HTML, plain text."
            )

    async def delete_document(self, doc_id: str) -> None:
        """Delete a document from Retriva by its doc_id.

        Raises on HTTP errors.
        """
        url = f"{self._base_url}/api/v1/documents/{doc_id}"
        response = await self._client.delete(url, headers=self._headers())
        response.raise_for_status()

        logger.info(f"retriva_deleted doc_id={doc_id}")

    async def health(self) -> bool:
        """Check if Retriva is reachable."""
        url = f"{self._base_url}/healthz"
        try:
            response = await self._client.get(url, headers=self._headers())
            return response.status_code == 200  # noqa: PLR2004
        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Format-specific ingestion
    # ------------------------------------------------------------------

    async def _ingest_pdf(self, fetched: FetchedFile) -> str:
        """Extract text from PDF and send page-by-page to Retriva."""
        extraction = extract_pdf(fetched.content, fetched.filename)
        if extraction is None:
            raise ValueError(
                f"Cannot extract text from PDF '{fetched.filename}' "
                f"(corrupt, encrypted, or empty)."
            )

        url = f"{self._base_url}/api/v1/ingest/pdf"
        doc_id = f"owui:{fetched.file_id}"
        job_ids: list[str] = []

        for page in extraction.pages:
            payload = {
                "source_path": doc_id,
                "page_title": extraction.title,
                "content_text": page.text,
                "page_number": page.page_number,
                "total_pages": extraction.total_pages,
            }

            response = await self._client.post(
                url, headers=self._headers(), json=payload,
            )
            response.raise_for_status()

            body = response.json()
            job_id = body.get("job_id", "")
            if job_id:
                job_ids.append(job_id)

            logger.debug(
                f"retriva_pdf_page_sent file_id={fetched.file_id} "
                f"page={page.page_number}/{extraction.total_pages} "
                f"job_id={job_id}"
            )

        logger.info(
            f"retriva_ingested file_id={fetched.file_id} "
            f"filename={fetched.filename} doc_id={doc_id} "
            f"pages={len(extraction.pages)} jobs={len(job_ids)}"
        )
        return doc_id

    async def _ingest_html(self, fetched: FetchedFile) -> str:
        """Decode HTML bytes and send to Retriva."""
        url = f"{self._base_url}/api/v1/ingest/html"
        doc_id = f"owui:{fetched.file_id}"

        html_content = fetched.content.decode("utf-8", errors="replace")
        payload = {
            "source_path": doc_id,
            "page_title": fetched.filename,
            "html_content": html_content,
        }

        response = await self._client.post(
            url, headers=self._headers(), json=payload,
        )
        response.raise_for_status()

        logger.info(
            f"retriva_ingested file_id={fetched.file_id} "
            f"filename={fetched.filename} doc_id={doc_id}"
        )
        return doc_id

    async def _ingest_text(self, fetched: FetchedFile) -> str:
        """Decode text bytes and send to Retriva."""
        url = f"{self._base_url}/api/v1/ingest/text"
        doc_id = f"owui:{fetched.file_id}"

        content_text = fetched.content.decode("utf-8", errors="replace")
        payload = {
            "source_path": doc_id,
            "page_title": fetched.filename,
            "content_text": content_text,
        }

        response = await self._client.post(
            url, headers=self._headers(), json=payload,
        )
        response.raise_for_status()

        logger.info(
            f"retriva_ingested file_id={fetched.file_id} "
            f"filename={fetched.filename} doc_id={doc_id}"
        )
        return doc_id
