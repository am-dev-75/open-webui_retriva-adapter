# SPDX-License-Identifier: MIT
"""File observer — polls Open WebUI to discover new and removed files."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from adapter.config import Settings
from adapter.models import OWUIFile

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FileChanges:
    """Result of comparing OWUI state against local mappings."""

    to_ingest: list[OWUIFile]
    to_delete: list[str]  # OWUI file IDs to delete


class FileObserver:
    """Polls Open WebUI ``/api/v1/files`` and computes a diff."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.OWUI_BASE_URL.rstrip("/")
        self._api_key = settings.OWUI_API_KEY
        self._client = client

    async def list_files(self) -> list[OWUIFile]:
        """Fetch the current file list from Open WebUI."""
        url = f"{self._base_url}/api/v1/files"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        response = await self._client.get(url, headers=headers)
        response.raise_for_status()

        raw_files = response.json()
        # OWUI returns a list of file objects
        if isinstance(raw_files, dict) and "data" in raw_files:
            raw_files = raw_files["data"]

        files: list[OWUIFile] = []
        for f in raw_files:
            meta = f.get("meta", {}) or {}
            files.append(
                OWUIFile(
                    id=f["id"],
                    filename=f.get("filename", meta.get("name", "unknown")),
                    content_type=meta.get("content_type", "application/octet-stream"),
                    size=meta.get("size", 0),
                    hash=f.get("hash", ""),
                    created_at=f.get("created_at", 0),
                ),
            )

        logger.debug("owui_files_listed", count=len(files))
        return files

    def detect_changes(
        self,
        owui_files: list[OWUIFile],
        synced_file_ids: set[str],
    ) -> FileChanges:
        """Compare OWUI files against synced mappings.

        Returns which files need to be ingested and which need deletion.
        """
        owui_ids = {f.id for f in owui_files}
        owui_lookup = {f.id: f for f in owui_files}

        to_ingest_ids = owui_ids - synced_file_ids
        to_delete_ids = synced_file_ids - owui_ids

        to_ingest = [owui_lookup[fid] for fid in to_ingest_ids]
        to_delete = list(to_delete_ids)

        logger.info(
            "changes_detected",
            new_files=len(to_ingest),
            removed_files=len(to_delete),
        )
        return FileChanges(to_ingest=to_ingest, to_delete=to_delete)
