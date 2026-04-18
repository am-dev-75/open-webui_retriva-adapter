# SPDX-License-Identifier: MIT
"""Tests for adapter.orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapter.mapping_store import MappingStore
from adapter.models import FetchedFile, OWUIFile
from adapter.observer import FileChanges
from adapter.orchestrator import SyncOrchestrator


@pytest.fixture
async def orchestrator_deps(tmp_path: Path):
    """Create mocked dependencies for the orchestrator."""
    store = MappingStore(tmp_path / "orch_test.db")
    await store.open()

    observer = AsyncMock()
    fetcher = AsyncMock()
    retriva = AsyncMock()

    orch = SyncOrchestrator(observer, fetcher, retriva, store)
    yield orch, observer, fetcher, retriva, store
    await store.close()


class TestSyncOrchestrator:
    """Orchestrator tests (T-16)."""

    async def test_happy_path_ingest(self, orchestrator_deps) -> None:
        orch, observer, fetcher, retriva, store = orchestrator_deps

        owui_file = OWUIFile(id="f-1", filename="report.pdf")
        fetched = FetchedFile(
            file_id="f-1", filename="report.pdf",
            content_type="application/pdf", content=b"hello", size=5,
        )

        observer.list_files = AsyncMock(return_value=[owui_file])
        observer.detect_changes = MagicMock(
            return_value=FileChanges(to_ingest=[owui_file], to_delete=[]),
        )
        fetcher.download = AsyncMock(return_value=fetched)
        retriva.ingest = AsyncMock(return_value="d-99")

        result = await orch.run_cycle()

        assert result.ingested == 1
        assert result.deleted == 0
        assert result.failed == 0

        mapping = await store.get_by_file_id("f-1")
        assert mapping is not None
        assert mapping.retriva_doc_id == "d-99"
        assert mapping.status == "synced"

    async def test_happy_path_delete(self, orchestrator_deps) -> None:
        orch, observer, fetcher, retriva, store = orchestrator_deps

        # Pre-create a mapping
        await store.create("f-old", "old.txt", "d-old")

        observer.list_files = AsyncMock(return_value=[])
        observer.detect_changes = MagicMock(
            return_value=FileChanges(to_ingest=[], to_delete=["f-old"]),
        )
        retriva.delete_document = AsyncMock()

        result = await orch.run_cycle()

        assert result.deleted == 1
        retriva.delete_document.assert_called_once_with("d-old")

    async def test_ingest_failure_creates_failed_mapping(self, orchestrator_deps) -> None:
        orch, observer, fetcher, retriva, store = orchestrator_deps

        owui_file = OWUIFile(id="f-fail", filename="fail.pdf")
        fetched = FetchedFile(
            file_id="f-fail", filename="fail.pdf",
            content_type="application/pdf", content=b"x", size=1,
        )

        observer.list_files = AsyncMock(return_value=[owui_file])
        observer.detect_changes = MagicMock(
            return_value=FileChanges(to_ingest=[owui_file], to_delete=[]),
        )
        fetcher.download = AsyncMock(return_value=fetched)
        retriva.ingest = AsyncMock(side_effect=Exception("retriva down"))

        result = await orch.run_cycle()

        assert result.failed == 1
        mapping = await store.get_by_file_id("f-fail")
        assert mapping is not None
        assert mapping.status == "failed"

    async def test_idempotent_no_duplicate(self, orchestrator_deps) -> None:
        orch, observer, fetcher, retriva, store = orchestrator_deps

        # File already synced
        await store.create("f-1", "a.txt", "d-1")

        observer.list_files = AsyncMock(
            return_value=[OWUIFile(id="f-1", filename="a.txt")],
        )
        observer.detect_changes = MagicMock(
            return_value=FileChanges(to_ingest=[], to_delete=[]),
        )

        result = await orch.run_cycle()

        assert result.ingested == 0
        fetcher.download.assert_not_called()
        retriva.ingest.assert_not_called()

    async def test_download_404_skips(self, orchestrator_deps) -> None:
        orch, observer, fetcher, retriva, store = orchestrator_deps

        owui_file = OWUIFile(id="f-gone", filename="gone.txt")
        observer.list_files = AsyncMock(return_value=[owui_file])
        observer.detect_changes = MagicMock(
            return_value=FileChanges(to_ingest=[owui_file], to_delete=[]),
        )
        fetcher.download = AsyncMock(return_value=None)  # 404

        result = await orch.run_cycle()

        assert result.skipped == 1
        assert result.ingested == 0
