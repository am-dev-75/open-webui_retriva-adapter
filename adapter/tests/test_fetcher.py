# SPDX-License-Identifier: MIT
"""Tests for adapter.fetcher."""

from __future__ import annotations

import httpx
import respx

from adapter.config import Settings
from adapter.fetcher import FileFetcher
from adapter.models import OWUIFile


class TestFileFetcher:
    """FileFetcher tests (T-11)."""

    @respx.mock
    async def test_download_success(self, settings: Settings) -> None:
        file_info = OWUIFile(id="f-1", filename="test.pdf", content_type="application/pdf")
        content = b"fake pdf content"

        respx.get(f"{settings.OWUI_BASE_URL}/api/v1/files/f-1/content").mock(
            return_value=httpx.Response(200, content=content),
        )
        async with httpx.AsyncClient() as client:
            fetcher = FileFetcher(settings, client)
            result = await fetcher.download(file_info)

        assert result is not None
        assert result.file_id == "f-1"
        assert result.content == content
        assert result.size == len(content)

    @respx.mock
    async def test_download_404_returns_none(self, settings: Settings) -> None:
        file_info = OWUIFile(id="f-gone", filename="gone.txt")

        respx.get(f"{settings.OWUI_BASE_URL}/api/v1/files/f-gone/content").mock(
            return_value=httpx.Response(404),
        )
        async with httpx.AsyncClient() as client:
            fetcher = FileFetcher(settings, client)
            result = await fetcher.download(file_info)

        assert result is None

    @respx.mock
    async def test_download_server_error_raises(self, settings: Settings) -> None:
        file_info = OWUIFile(id="f-err", filename="err.txt")

        respx.get(f"{settings.OWUI_BASE_URL}/api/v1/files/f-err/content").mock(
            return_value=httpx.Response(500),
        )
        async with httpx.AsyncClient() as client:
            fetcher = FileFetcher(settings, client)
            try:
                await fetcher.download(file_info)
                assert False, "Should have raised"  # noqa: B011
            except httpx.HTTPStatusError as exc:
                assert exc.response.status_code == 500  # noqa: PLR2004
