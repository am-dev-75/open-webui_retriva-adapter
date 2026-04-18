# SPDX-License-Identifier: MIT
"""Retriva API client — forwards files for ingestion and propagates deletions."""

from __future__ import annotations

import httpx
import structlog

from adapter.config import Settings
from adapter.models import FetchedFile

logger = structlog.get_logger(__name__)


class RetrivaClient:
    """HTTP client for Retriva ingestion and document management."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.RETRIVA_BASE_URL.rstrip("/")
        self._api_key = settings.RETRIVA_API_KEY
        self._client = client

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def ingest(self, fetched: FetchedFile) -> str:
        """Forward a file to Retriva for ingestion.

        Returns the ``doc_id`` assigned by Retriva.
        Raises on HTTP errors.
        """
        url = f"{self._base_url}/api/v1/ingest"

        files = {
            "file": (fetched.filename, fetched.content, fetched.content_type),
        }
        data = {
            "source": "openwebui",
            "source_file_id": fetched.file_id,
            "filename": fetched.filename,
        }

        response = await self._client.post(
            url,
            headers=self._headers(),
            files=files,
            data=data,
        )
        response.raise_for_status()

        body = response.json()
        # Retriva may return doc_id directly or inside a wrapper
        doc_id: str = body.get("doc_id") or body.get("id") or str(body)

        logger.info(
            "retriva_ingested",
            file_id=fetched.file_id,
            filename=fetched.filename,
            doc_id=doc_id,
        )
        return doc_id

    async def delete_document(self, doc_id: str) -> None:
        """Delete a document from Retriva by its doc_id.

        Raises on HTTP errors.
        """
        url = f"{self._base_url}/api/v1/documents/{doc_id}"
        response = await self._client.delete(url, headers=self._headers())
        response.raise_for_status()

        logger.info("retriva_deleted", doc_id=doc_id)

    async def health(self) -> bool:
        """Check if Retriva is reachable."""
        url = f"{self._base_url}/healthz"
        try:
            response = await self._client.get(url, headers=self._headers())
            return response.status_code == 200  # noqa: PLR2004
        except httpx.HTTPError:
            return False
