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

"""Retriva API client — forwards files for ingestion and propagates deletions.

Routes files to the correct format-specific Retriva endpoint based on
content type. The adapter does not parse files itself; it delegates all
extraction and chunking to the Retriva backend.
"""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from adapter.config import Settings
from adapter.models import FetchedFile

from adapter.logger import get_logger

logger = get_logger(__name__)

# Routing table: content type prefix/exact -> endpoint path
_ROUTING_TABLE = {
    "application/pdf": "/api/v1/ingest/upload/pdf",
    "text/plain": "/api/v1/ingest/text",
    "text/markdown": "/api/v1/ingest/markdown",
    "application/markdown": "/api/v1/ingest/markdown",
    "text/csv": "/api/v1/ingest/text",
    "text/html": "/api/v1/ingest/html",
    "application/xhtml+xml": "/api/v1/ingest/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "/api/v1/ingest/docx",
    "image/": "/api/v1/ingest/image",
}


class RetrivaClient(Protocol):
    """Protocol for Retriva ingestion and document management clients."""
    
    async def ingest(self, fetched: FetchedFile) -> str:
        ...

    async def delete_document(self, doc_id: str) -> None:
        ...

    async def health(self) -> bool:
        ...

    async def generate_artifact(
        self,
        artifact_type: str,
        format: str,
        parameters: dict[str, Any] | None = None,
        user_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class RetrivaClientV1:
    """HTTP client for Retriva ingestion API v1."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.retriva_ingestion_url
        self._api_key = settings.RETRIVA_API_KEY
        self._client = client

    def _auth_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
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
        
        endpoint_path = self._determine_endpoint(content_type)
        if not endpoint_path:
            raise ValueError(
                f"Unsupported content type '{content_type}' for file "
                f"'{fetched.filename}'."
            )

        return await self._forward_multipart(fetched, endpoint_path, content_type)

    async def delete_document(self, doc_id: str) -> None:
        """Delete a document from Retriva by its doc_id.

        Raises on HTTP errors.
        """
        url = f"{self._base_url}/api/v1/documents/{doc_id}"
        response = await self._client.delete(url, headers=self._auth_headers())
        response.raise_for_status()

        logger.info(f"retriva_deleted doc_id={doc_id}")

    async def health(self) -> bool:
        """Check if Retriva is reachable."""
        url = f"{self._base_url}/healthz"
        try:
            response = await self._client.get(url, headers=self._auth_headers())
            return response.status_code == 200  # noqa: PLR2004
        except httpx.HTTPError:
            return False

    async def generate_artifact(
        self,
        artifact_type: str,
        format: str,
        parameters: dict[str, Any] | None = None,
        user_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Artifacts are not supported in Retriva API v1."""
        raise NotImplementedError("Artifact generation requires Retriva API v2.")

    # ------------------------------------------------------------------
    # Format-specific routing
    # ------------------------------------------------------------------

    def _determine_endpoint(self, content_type: str) -> str | None:
        """Find the matching Retriva ingestion endpoint for the content type."""
        for key, path in _ROUTING_TABLE.items():
            if content_type == key or (key.endswith("/") and content_type.startswith(key)):
                return path
        return None

    async def _forward_multipart(
        self, fetched: FetchedFile, endpoint_path: str, content_type: str,
    ) -> str:
        """Send the file as a multipart/form-data upload to Retriva."""
        url = f"{self._base_url}{endpoint_path}"
        doc_id = f"owui:{fetched.file_id}"

        # Typically Retriva expects the file as 'file' and metadata as 'data'
        files = {
            "file": (fetched.filename, fetched.content, content_type),
        }
        data = {
            "source_path": doc_id,
            "page_title": fetched.filename,
        }

        # Forward metadata when present (Pattern A + revised Pattern D)
        if fetched.kb_ids:
            data["kb_ids"] = json.dumps(list(fetched.kb_ids))
        logger.debug(f"DEBUG: RetrivaClient._forward_multipart user_metadata={fetched.user_metadata!r}")
        if fetched.user_metadata:
            metadata_json = json.dumps(fetched.metadata_dict())
            logger.debug(f"DEBUG: RetrivaClient sending user_metadata={metadata_json!r}")
            data["user_metadata"] = metadata_json

        response = await self._client.post(
            url,
            headers=self._auth_headers(),
            data=data,
            files=files,
        )
        response.raise_for_status()

        body = response.json()
        job_id = body.get("job_id", "")

        logger.info(
            f"retriva_ingested file_id={fetched.file_id} "
            f"filename={fetched.filename} doc_id={doc_id} "
            f"endpoint={endpoint_path} job_id={job_id}"
        )
        return doc_id


class RetrivaClientV2:
    """HTTP client for Retriva ingestion API v2."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.retriva_ingestion_url
        self._api_key = settings.RETRIVA_API_KEY
        self._client = client

    def _auth_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def ingest(self, fetched: FetchedFile) -> str:
        content_type = (fetched.content_type or "").split(";")[0].strip().lower()
        url = f"{self._base_url}/api/v2/documents/upload"
        doc_id = f"owui:{fetched.file_id}"

        files = {
            "file": (fetched.filename, fetched.content, content_type),
        }
        data = {
            "source_path": doc_id,
            "page_title": fetched.filename,
        }

        if fetched.kb_ids:
            data["kb_ids"] = json.dumps(list(fetched.kb_ids))
        if fetched.user_metadata:
            data["user_metadata"] = json.dumps(fetched.metadata_dict())

        response = await self._client.post(
            url,
            headers=self._auth_headers(),
            data=data,
            files=files,
        )
        response.raise_for_status()

        body = response.json()
        job_id = body.get("job_id", "")

        logger.info(
            f"retriva_ingested_v2 file_id={fetched.file_id} "
            f"filename={fetched.filename} doc_id={doc_id} "
            f"job_id={job_id}"
        )
        return doc_id

    async def delete_document(self, doc_id: str) -> None:
        url = f"{self._base_url}/api/v2/documents/{doc_id}"
        response = await self._client.delete(url, headers=self._auth_headers())
        response.raise_for_status()

    async def get_artifact_status(self, artifact_id: str) -> dict[str, Any]:
        """Poll the status of an artifact generation job."""
        url = f"{self._base_url}/api/v2/artifacts/{artifact_id}"
        response = await self._client.get(url, headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

        logger.info(f"retriva_deleted_v2 doc_id={doc_id}")

    async def health(self) -> bool:
        url = f"{self._base_url}/healthz"
        try:
            response = await self._client.get(url, headers=self._auth_headers())
            return response.status_code == 200  # noqa: PLR2004
        except httpx.HTTPError:
            return False

    async def generate_artifact(
        self,
        artifact_type: str,
        format: str,
        parameters: dict[str, Any] | None = None,
        user_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Initiate artifact generation via Retriva API v2."""
        url = f"{self._base_url}/api/v2/artifacts"
        
        payload = {
            "artifact_type": artifact_type,
            "format": format,
            "parameters": parameters or {},
            "user_metadata": user_metadata or {},
        }
        
        response = await self._client.post(
            url,
            headers=self._auth_headers(),
            json=payload,
        )
        response.raise_for_status()
        
        return response.json()


def create_retriva_client(settings: Settings, client: httpx.AsyncClient) -> RetrivaClient:
    """Factory to create the appropriate RetrivaClient version."""
    if settings.RETRIVA_INGESTION_API_VERSION.lower() == "v2":
        return RetrivaClientV2(settings, client)
    return RetrivaClientV1(settings, client)
