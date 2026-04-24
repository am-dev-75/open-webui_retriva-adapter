# SPDX-License-Identifier: MIT
"""Integration tests — validate upload, ingest, query, and delete flows.

These tests wire all real components together (observer, fetcher, Retriva
client, orchestrator, mapping store) with only the HTTP layer mocked via
respx. SQLite is real (in-memory temp path).

The adapter routes files to format-specific Retriva endpoints based on
content type. For PDFs and other files, they are forwarded directly via
multipart uploads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from adapter.config import Settings
from adapter.fetcher import FileFetcher
from adapter.mapping_store import MappingStore
from adapter.observer import FileObserver
from adapter.orchestrator import SyncOrchestrator
from adapter.retriva_client import RetrivaClient


@pytest.fixture
def int_settings(tmp_path: Path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_BASE_URL="http://retriva:8400",
        DB_PATH=tmp_path / "integration.db",
        POLL_INTERVAL_SECONDS=5,
    )


@pytest.fixture
async def int_stack(int_settings: Settings):
    """Build a fully wired component stack with a real SQLite store."""
    store = MappingStore(int_settings.DB_PATH)
    await store.open()

    async with httpx.AsyncClient() as client:
        observer = FileObserver(int_settings, client)
        fetcher = FileFetcher(int_settings, client)
        retriva = RetrivaClient(int_settings, client)
        orchestrator = SyncOrchestrator(observer, fetcher, retriva, store)

        yield {
            "settings": int_settings,
            "store": store,
            "observer": observer,
            "fetcher": fetcher,
            "retriva": retriva,
            "orchestrator": orchestrator,
        }

    await store.close()


# ──────────────────────────────────────────────────────────────────────
# Flow 1: Upload Detection + Ingestion
# ──────────────────────────────────────────────────────────────────────

class TestUploadAndIngestFlow:
    """Validate: file appears in OWUI → adapter downloads → ingests into Retriva."""

    @respx.mock
    async def test_new_file_is_detected_downloaded_and_ingested(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]

        # OWUI returns one file (PDF)
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {
                    "id": "file-abc",
                    "filename": "report.pdf",
                    "hash": "deadbeef",
                    "meta": {
                        "content_type": "application/pdf",
                        "size": 1024,
                    },
                    "created_at": 1700000000000,
                },
            ]),
        )

        # File download returns content
        file_content = b"%PDF-1.4 fake pdf content for testing"
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/file-abc/content").mock(
            return_value=httpx.Response(200, content=file_content),
        )

        # Retriva PDF ingestion endpoint
        respx.post(f"{s.RETRIVA_BASE_URL}/api/v1/ingest/upload/pdf").mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-1"},
            ),
        )

        result = await int_stack["orchestrator"].run_cycle()

        # Verify result
        assert result.ingested == 1
        assert result.failed == 0
        assert result.deleted == 0

        # Verify mapping was created correctly
        mapping = await int_stack["store"].get_by_file_id("file-abc")
        assert mapping is not None
        assert mapping.filename == "report.pdf"
        assert mapping.retriva_doc_id == "owui:file-abc"
        assert mapping.status == "synced"
        assert mapping.content_hash != ""  # SHA-256 was computed

    @respx.mock
    async def test_multiple_files_ingested_in_single_cycle(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {"id": "f1", "filename": "a.txt", "meta": {"content_type": "text/plain"}},
                {"id": "f2", "filename": "b.pdf", "meta": {"content_type": "application/pdf"}},
                {"id": "f3", "filename": "c.md", "meta": {"content_type": "text/plain"}},
            ]),
        )

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f1/content").mock(
            return_value=httpx.Response(200, content=b"content-a"),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f2/content").mock(
            return_value=httpx.Response(200, content=b"content-b"),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f3/content").mock(
            return_value=httpx.Response(200, content=b"content-c"),
        )

        # Text endpoint for .txt and .md files
        respx.post(f"{s.RETRIVA_BASE_URL}/api/v1/ingest/text").mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-t"},
            ),
        )
        # PDF endpoint for .pdf files
        respx.post(f"{s.RETRIVA_BASE_URL}/api/v1/ingest/upload/pdf").mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-p"},
            ),
        )

        result = await int_stack["orchestrator"].run_cycle()

        assert result.ingested == 3
        assert result.failed == 0

        all_mappings = await int_stack["store"].list_all()
        assert len(all_mappings) == 3
        assert all(m.status == "synced" for m in all_mappings)


# ──────────────────────────────────────────────────────────────────────
# Flow 2: Idempotent Re-sync (no duplicates)
# ──────────────────────────────────────────────────────────────────────

class TestIdempotencyFlow:
    """Validate: re-running a cycle does not duplicate ingestions."""

    @respx.mock
    async def test_second_cycle_does_not_reingest(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        # Pre-create a mapping (simulating a previous successful sync)
        await store.create("file-existing", "old.pdf", "doc-existing")

        # OWUI still has the same file
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {"id": "file-existing", "filename": "old.pdf", "meta": {}},
            ]),
        )

        # These should NOT be called
        download_route = respx.get(
            f"{s.OWUI_BASE_URL}/api/v1/files/file-existing/content",
        ).mock(return_value=httpx.Response(200, content=b"x"))
        ingest_route = respx.post(
            f"{s.RETRIVA_BASE_URL}/api/v1/ingest/text",
        ).mock(return_value=httpx.Response(202, json={"status": "accepted", "message": "ok"}))

        result = await int_stack["orchestrator"].run_cycle()

        assert result.ingested == 0
        assert result.deleted == 0
        assert download_route.call_count == 0
        assert ingest_route.call_count == 0

        # Mapping count unchanged
        all_mappings = await store.list_all()
        assert len(all_mappings) == 1


# ──────────────────────────────────────────────────────────────────────
# Flow 3: Query Mappings
# ──────────────────────────────────────────────────────────────────────

class TestQueryMappingsFlow:
    """Validate: mappings are queryable and reflect accurate state."""

    async def test_mappings_reflect_sync_state(
        self, int_stack: dict,
    ) -> None:
        store = int_stack["store"]

        await store.create("f-1", "a.pdf", "d-1", status="synced")
        await store.create("f-2", "b.txt", "", status="failed")

        all_records = await store.list_all()
        assert len(all_records) == 2

        synced = await store.list_all(status="synced")
        assert len(synced) == 1
        assert synced[0].owui_file_id == "f-1"

        failed = await store.list_all(status="failed")
        assert len(failed) == 1
        assert failed[0].owui_file_id == "f-2"

    async def test_synced_file_ids_set(self, int_stack: dict) -> None:
        store = int_stack["store"]

        await store.create("f-a", "a.pdf", "d-a", status="synced")
        await store.create("f-b", "b.pdf", "d-b", status="synced")
        await store.create("f-c", "c.pdf", "", status="failed")

        ids = await store.get_synced_file_ids()
        assert ids == {"f-a", "f-b"}
        assert "f-c" not in ids


# ──────────────────────────────────────────────────────────────────────
# Flow 4: Delete Propagation
# ──────────────────────────────────────────────────────────────────────

class TestDeleteFlow:
    """Validate: file removed from OWUI → Retriva doc deleted → mapping cleaned."""

    @respx.mock
    async def test_removed_file_triggers_retriva_delete(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        # Pre-create a synced mapping
        await store.create("file-to-delete", "deleteme.pdf", "doc-del-001")

        # OWUI no longer has this file
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[]),
        )

        # Retriva delete should be called
        delete_route = respx.delete(
            f"{s.RETRIVA_BASE_URL}/api/v1/documents/doc-del-001",
        ).mock(return_value=httpx.Response(200))

        result = await int_stack["orchestrator"].run_cycle()

        assert result.deleted == 1
        assert result.failed == 0
        assert delete_route.call_count == 1

        # Mapping should be pruned (deleted then pruned in same cycle)
        remaining = await store.list_all(status="synced")
        assert len(remaining) == 0

    @respx.mock
    async def test_delete_multiple_files(self, int_stack: dict) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        await store.create("f-del-1", "one.pdf", "doc-1")
        await store.create("f-del-2", "two.pdf", "doc-2")
        await store.create("f-keep", "keep.pdf", "doc-keep")

        # OWUI only has f-keep
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {"id": "f-keep", "filename": "keep.pdf", "meta": {}},
            ]),
        )

        respx.delete(f"{s.RETRIVA_BASE_URL}/api/v1/documents/doc-1").mock(
            return_value=httpx.Response(200),
        )
        respx.delete(f"{s.RETRIVA_BASE_URL}/api/v1/documents/doc-2").mock(
            return_value=httpx.Response(200),
        )

        result = await int_stack["orchestrator"].run_cycle()

        assert result.deleted == 2
        synced = await store.list_all(status="synced")
        assert len(synced) == 1
        assert synced[0].owui_file_id == "f-keep"

    @respx.mock
    async def test_delete_failure_preserves_mapping(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        await store.create("f-stubborn", "stubborn.pdf", "doc-stubborn")

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[]),
        )

        # Retriva delete fails
        respx.delete(
            f"{s.RETRIVA_BASE_URL}/api/v1/documents/doc-stubborn",
        ).mock(return_value=httpx.Response(500))

        result = await int_stack["orchestrator"].run_cycle()

        assert result.failed == 1

        # Mapping should still exist (not pruned because delete failed)
        mapping = await store.get_by_file_id("f-stubborn")
        assert mapping is not None


# ──────────────────────────────────────────────────────────────────────
# Flow 5: Failed Ingestion Retry
# ──────────────────────────────────────────────────────────────────────

class TestRetryFlow:
    """Validate: failed ingestion is retried on the next cycle."""

    @respx.mock
    async def test_failed_ingestion_retried_and_succeeds(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        # --- Cycle 1: file appears, ingestion fails ---
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/").mock(
            return_value=httpx.Response(200, json=[
                {
                    "id": "f-retry",
                    "filename": "retry.txt",
                    "meta": {"content_type": "text/plain"},
                },
            ]),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f-retry/content").mock(
            return_value=httpx.Response(200, content=b"retry content"),
        )

        # Calls 1 and 2 fail (initial + in-cycle retry), call 3+ succeed
        call_count = 0

        def ingest_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(503, json={"error": "overloaded"})
            return httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-retry"},
            )

        respx.post(f"{s.RETRIVA_BASE_URL}/api/v1/ingest/text").mock(
            side_effect=ingest_handler,
        )

        result1 = await int_stack["orchestrator"].run_cycle()
        assert result1.failed == 1

        mapping = await store.get_by_file_id("f-retry")
        assert mapping is not None
        assert mapping.status == "failed"

        # --- Cycle 2: retry succeeds ---

        result2 = await int_stack["orchestrator"].run_cycle()

        # The retry should have succeeded
        assert result2.retried == 1

        mapping = await store.get_by_file_id("f-retry")
        assert mapping is not None
        assert mapping.status == "synced"
        assert mapping.retriva_doc_id == "owui:f-retry"


# ──────────────────────────────────────────────────────────────────────
# Flow 6: Full Lifecycle (upload → sync → delete)
# ──────────────────────────────────────────────────────────────────────

class TestFullLifecycleFlow:
    """Validate the complete file lifecycle across multiple sync cycles."""

    @respx.mock
    async def test_upload_then_delete_lifecycle(
        self, int_stack: dict,
    ) -> None:
        s = int_stack["settings"]
        store = int_stack["store"]

        # --- Cycle 1: File appears in OWUI → ingested ---

        file_list_route = respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/")
        file_list_route.mock(
            return_value=httpx.Response(200, json=[
                {
                    "id": "f-lifecycle",
                    "filename": "lifecycle.txt",
                    "meta": {"content_type": "text/plain"},
                },
            ]),
        )
        respx.get(
            f"{s.OWUI_BASE_URL}/api/v1/files/f-lifecycle/content",
        ).mock(return_value=httpx.Response(200, content=b"lifecycle data"))
        respx.post(f"{s.RETRIVA_BASE_URL}/api/v1/ingest/text").mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-lc"},
            ),
        )

        r1 = await int_stack["orchestrator"].run_cycle()
        assert r1.ingested == 1

        # Verify mapping
        m = await store.get_by_file_id("f-lifecycle")
        assert m is not None
        assert m.status == "synced"
        assert m.retriva_doc_id == "owui:f-lifecycle"

        # --- Cycle 2: Same file still present → no-op ---

        r2 = await int_stack["orchestrator"].run_cycle()
        assert r2.ingested == 0
        assert r2.deleted == 0

        # --- Cycle 3: File removed from OWUI → deleted from Retriva ---

        file_list_route.mock(
            return_value=httpx.Response(200, json=[]),
        )
        delete_route = respx.delete(
            f"{s.RETRIVA_BASE_URL}/api/v1/documents/owui:f-lifecycle",
        ).mock(return_value=httpx.Response(200))

        r3 = await int_stack["orchestrator"].run_cycle()
        assert r3.deleted == 1
        assert delete_route.call_count == 1

        # Mapping should be fully pruned
        remaining = await store.list_all(status="synced")
        assert len(remaining) == 0
