# SPDX-License-Identifier: MIT
"""File fetcher — downloads raw file content from Open WebUI."""

from __future__ import annotations

import httpx
import structlog

from adapter.config import Settings
from adapter.models import FetchedFile, OWUIFile

logger = structlog.get_logger(__name__)


class FileFetcher:
    """Downloads file bytes from Open WebUI ``/api/v1/files/{id}/content``."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.OWUI_BASE_URL.rstrip("/")
        self._api_key = settings.OWUI_API_KEY
        self._client = client

    async def download(self, file_info: OWUIFile) -> FetchedFile | None:
        """Download a single file from OWUI.

        Returns ``None`` if the file no longer exists (404).
        Raises on other HTTP errors after exhausting retries upstream.
        """
        url = f"{self._base_url}/api/v1/files/{file_info.id}/content"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            response = await self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.error(
                "file_download_error",
                file_id=file_info.id,
                filename=file_info.filename,
                error=str(exc),
            )
            raise

        if response.status_code == 404:
            logger.info(
                "file_not_found",
                file_id=file_info.id,
                filename=file_info.filename,
            )
            return None

        response.raise_for_status()

        content = response.content
        fetched = FetchedFile(
            file_id=file_info.id,
            filename=file_info.filename,
            content_type=file_info.content_type,
            content=content,
            size=len(content),
        )
        logger.info(
            "file_downloaded",
            file_id=file_info.id,
            filename=file_info.filename,
            size=fetched.size,
        )
        return fetched
