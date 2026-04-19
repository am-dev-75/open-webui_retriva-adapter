# SPDX-License-Identifier: MIT
"""Tests for adapter.observer."""

from __future__ import annotations

import httpx
import pytest
import respx

from adapter.config import Settings
from adapter.models import OWUIFile
from adapter.observer import FileObserver


@pytest.fixture
def observer(settings: Settings) -> FileObserver:
    client = httpx.AsyncClient()
    return FileObserver(settings, client)


class TestFileObserver:
    """FileObserver tests (T-09)."""

    @respx.mock
    async def test_list_files_bare_list(self, settings: Settings) -> None:
        """OWUI returns a bare JSON list."""
        respx.get(f"{settings.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {
                    "id": "f-1",
                    "filename": "doc.pdf",
                    "hash": "h1",
                    "meta": {"content_type": "application/pdf", "size": 100},
                    "created_at": 1000,
                },
            ]),
        )
        async with httpx.AsyncClient() as client:
            obs = FileObserver(settings, client)
            files = await obs.list_files()

        assert len(files) == 1
        assert files[0].id == "f-1"
        assert files[0].filename == "doc.pdf"
        assert files[0].content_type == "application/pdf"

    @respx.mock
    async def test_list_files_wrapped(self, settings: Settings) -> None:
        """OWUI returns files in a {data: [...]} wrapper."""
        respx.get(f"{settings.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json={
                "data": [{"id": "f-2", "filename": "notes.txt", "meta": {}}],
            }),
        )
        async with httpx.AsyncClient() as client:
            obs = FileObserver(settings, client)
            files = await obs.list_files()

        assert len(files) == 1
        assert files[0].id == "f-2"

    def test_detect_changes_new_files(self, observer: FileObserver) -> None:
        owui = [OWUIFile(id="f-1", filename="a.txt"), OWUIFile(id="f-2", filename="b.txt")]
        synced = set()
        changes = observer.detect_changes(owui, synced)
        assert len(changes.to_ingest) == 2
        assert len(changes.to_delete) == 0

    def test_detect_changes_removed_files(self, observer: FileObserver) -> None:
        owui: list[OWUIFile] = []
        synced = {"f-old"}
        changes = observer.detect_changes(owui, synced)
        assert len(changes.to_ingest) == 0
        assert changes.to_delete == ["f-old"]

    def test_detect_changes_no_op(self, observer: FileObserver) -> None:
        owui = [OWUIFile(id="f-1", filename="a.txt")]
        synced = {"f-1"}
        changes = observer.detect_changes(owui, synced)
        assert len(changes.to_ingest) == 0
        assert len(changes.to_delete) == 0

    def test_detect_changes_mixed(self, observer: FileObserver) -> None:
        owui = [OWUIFile(id="f-1", filename="a.txt"), OWUIFile(id="f-new", filename="new.txt")]
        synced = {"f-1", "f-gone"}
        changes = observer.detect_changes(owui, synced)
        assert len(changes.to_ingest) == 1
        assert changes.to_ingest[0].id == "f-new"
        assert changes.to_delete == ["f-gone"]
