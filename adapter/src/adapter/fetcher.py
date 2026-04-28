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

"""File fetcher — downloads raw file content from Open WebUI."""

from __future__ import annotations

import httpx


from adapter.config import Settings
from adapter.models import FetchedFile, OWUIFile

from adapter.logger import get_logger

logger = get_logger(__name__)


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
            logger.error(f"file_download_error file_id={file_info.id} filename={file_info.filename} error={exc}")
            raise

        if response.status_code == 404:
            logger.info(f"file_not_found file_id={file_info.id} filename={file_info.filename}")
            return None

        response.raise_for_status()

        content = response.content

        # Prefer the HTTP response content-type when the OWUIFile has the
        # generic default.  This matters for the webhook ingestion path
        # where file metadata is not available upfront.
        content_type = file_info.content_type
        if content_type == "application/octet-stream":
            resp_ct = response.headers.get("content-type", "")
            if resp_ct:
                content_type = resp_ct.split(";")[0].strip()

        fetched = FetchedFile(
            file_id=file_info.id,
            filename=file_info.filename,
            content_type=content_type,
            content=content,
            size=len(content),
        )
        logger.info(f"file_downloaded file_id={file_info.id} filename={file_info.filename} size={fetched.size}")
        return fetched