# SPDX-License-Identifier: MIT
"""Verification — Upload files under different tagging contexts and confirm
metadata propagation to the Retriva ingestion API.

This test module simulates the full user journey:

  Scenario A: No tagging active → file ingested WITHOUT user_metadata
  Scenario B: Tagging active → file ingested WITH user_metadata + kb_ids
  Scenario C: Second tag_start replaces metadata → new file gets NEW metadata only
  Scenario D: tag_stop disables → file ingested WITHOUT user_metadata, kb_ids persist
  Scenario E: Default KB fallback → no kb_ids in webhook → DEFAULT_KB_ID used
  Scenario F: Multiple files in one webhook → all get same context
  Scenario G: Two chats in parallel → isolated contexts

Each scenario captures the raw multipart request sent to Retriva and
inspects the form fields for correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import ANY

import httpx
import pytest
import respx

from adapter.config import Settings
from adapter.directive_parser import DirectiveResult, parse_directive
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.mapping_store import MappingStore
from adapter.observer import FileObserver
from adapter.orchestrator import SyncOrchestrator
from adapter.retriva_client import RetrivaClient


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _extract_form_fields(request: httpx.Request) -> dict[str, str]:
    """Extract form-data field values from a multipart request body.

    Returns a dict of field-name → value-string for text fields.
    Binary file parts are excluded.
    """
    body = request.content
    content_type = request.headers.get("content-type", "")

    # Extract boundary from content-type header
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip('"')
            break
    else:
        return {}

    fields: dict[str, str] = {}
    parts = body.split(f"--{boundary}".encode())

    for raw_part in parts:
        decoded = raw_part.decode("utf-8", errors="replace")
        if 'name="' not in decoded:
            continue

        # Extract field name
        name_start = decoded.index('name="') + 6
        name_end = decoded.index('"', name_start)
        name = decoded[name_start:name_end]

        # Skip file uploads (they have filename=)
        if "filename=" in decoded.split("\r\n\r\n")[0]:
            continue

        # Extract value (after double CRLF)
        if "\r\n\r\n" in decoded:
            value = decoded.split("\r\n\r\n", 1)[1].rstrip("\r\n-")
            fields[name] = value

    return fields


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def v_settings(tmp_path: Path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_BASE_URL="http://retriva:8400",
        DB_PATH=tmp_path / "verify.db",
        POLL_INTERVAL_SECONDS=5,
        DEFAULT_KB_ID="kb-default",
    )


@pytest.fixture
async def v_stack(v_settings: Settings):
    store = MappingStore(v_settings.DB_PATH)
    await store.open()

    ctx = IngestionContext(default_kb_id=v_settings.DEFAULT_KB_ID)

    async with httpx.AsyncClient() as client:
        observer = FileObserver(v_settings, client)
        fetcher = FileFetcher(v_settings, client)
        retriva = RetrivaClient(v_settings, client)
        orchestrator = SyncOrchestrator(
            observer, fetcher, retriva, store,
            ingestion_context=ctx,
        )
        yield {
            "s": v_settings, "store": store, "ctx": ctx,
            "orch": orchestrator,
        }

    await store.close()


def _mock_download(base_url: str, file_id: str, content: bytes = b"data") -> None:
    """Register a mock for downloading a file from OWUI."""
    respx.get(f"{base_url}/api/v1/files/{file_id}/content").mock(
        return_value=httpx.Response(
            200, content=content,
            headers={"content-type": "text/plain"},
        ),
    )


def _mock_ingest(base_url: str) -> respx.Route:
    """Register a mock for the Retriva text ingestion endpoint."""
    return respx.post(f"{base_url}/api/v1/ingest/text").mock(
        return_value=httpx.Response(
            202, json={"status": "accepted", "message": "ok", "job_id": "j-v"},
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Scenario A: No tagging → no user_metadata
# ──────────────────────────────────────────────────────────────────────

class TestScenarioA_NoTagging:
    """File uploaded with no active tagging context."""

    @respx.mock
    async def test_file_ingested_without_user_metadata(self, v_stack: dict) -> None:
        s = v_stack["s"]
        _mock_download(s.OWUI_BASE_URL, "f-a1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-a1"], "chat-a")

        assert result.ingested == 1
        fields = _extract_form_fields(route.calls[0].request)

        # kb_ids should fall back to DEFAULT_KB_ID
        assert "kb_ids" in fields
        kb_ids = json.loads(fields["kb_ids"])
        assert kb_ids == ["kb-default"]

        # user_metadata should NOT be present (no tagging active)
        assert "user_metadata" not in fields

        # source_path and page_title always present
        assert "source_path" in fields
        assert "page_title" in fields


# ──────────────────────────────────────────────────────────────────────
# Scenario B: Tagging active → user_metadata + kb_ids
# ──────────────────────────────────────────────────────────────────────

class TestScenarioB_TaggingActive:
    """File uploaded while tagging is active."""

    @respx.mock
    async def test_file_carries_metadata_and_kb_ids(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # Activate tagging
        ctx.set_kb_ids("chat-b", ["kb-research", "kb-eng"])
        ctx.apply_directive("chat-b", DirectiveResult(
            action="tag_start",
            metadata={"project": "Apollo", "milestone": "M4", "owner": "alice"},
        ))

        _mock_download(s.OWUI_BASE_URL, "f-b1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-b1"], "chat-b")

        assert result.ingested == 1
        fields = _extract_form_fields(route.calls[0].request)

        # Verify kb_ids
        kb_ids = json.loads(fields["kb_ids"])
        assert set(kb_ids) == {"kb-research", "kb-eng"}

        # Verify user_metadata
        meta = json.loads(fields["user_metadata"])
        assert meta == {"project": "Apollo", "milestone": "M4", "owner": "alice"}


# ──────────────────────────────────────────────────────────────────────
# Scenario C: Second tag_start replaces metadata
# ──────────────────────────────────────────────────────────────────────

class TestScenarioC_MetadataReplacement:
    """Second @@ingestion_tag_start replaces metadata entirely — no merge."""

    @respx.mock
    async def test_replacement_not_merge(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # First tag_start
        ctx.apply_directive("chat-c", DirectiveResult(
            action="tag_start",
            metadata={"project": "Alpha", "phase": "design", "team": "red"},
        ))

        # Second tag_start — completely different keys
        ctx.apply_directive("chat-c", DirectiveResult(
            action="tag_start",
            metadata={"project": "Beta", "sprint": "42"},
        ))

        _mock_download(s.OWUI_BASE_URL, "f-c1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-c1"], "chat-c")

        assert result.ingested == 1
        meta = json.loads(
            _extract_form_fields(route.calls[0].request)["user_metadata"]
        )

        # Only the SECOND tag_start's keys should be present
        assert meta == {"project": "Beta", "sprint": "42"}

        # Keys from the first tag_start must be GONE
        assert "phase" not in meta
        assert "team" not in meta


# ──────────────────────────────────────────────────────────────────────
# Scenario D: tag_stop disables metadata, kb_ids persist
# ──────────────────────────────────────────────────────────────────────

class TestScenarioD_TagStop:
    """After @@ingestion_tag_stop, metadata cleared but kb_ids survive."""

    @respx.mock
    async def test_metadata_cleared_kb_ids_persist(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # Activate with metadata + KB IDs
        ctx.set_kb_ids("chat-d", ["kb-ops"])
        ctx.apply_directive("chat-d", DirectiveResult(
            action="tag_start",
            metadata={"env": "staging"},
        ))

        # Deactivate
        ctx.apply_directive("chat-d", DirectiveResult(action="tag_stop"))

        # Confirm state
        assert ctx.is_active("chat-d") is False
        assert ctx.get_metadata("chat-d") is None
        assert ctx.get_kb_ids("chat-d") == ["kb-ops"]  # persisted!

        _mock_download(s.OWUI_BASE_URL, "f-d1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-d1"], "chat-d")

        assert result.ingested == 1
        fields = _extract_form_fields(route.calls[0].request)

        # kb_ids still present
        kb_ids = json.loads(fields["kb_ids"])
        assert kb_ids == ["kb-ops"]

        # user_metadata should NOT be present (tagging inactive)
        assert "user_metadata" not in fields


# ──────────────────────────────────────────────────────────────────────
# Scenario E: Default KB fallback
# ──────────────────────────────────────────────────────────────────────

class TestScenarioE_DefaultKBFallback:
    """When no kb_ids provided, DEFAULT_KB_ID is used."""

    @respx.mock
    async def test_default_kb_id_fallback(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # Activate tagging but do NOT set any kb_ids
        ctx.apply_directive("chat-e", DirectiveResult(
            action="tag_start",
            metadata={"project": "Gamma"},
        ))

        _mock_download(s.OWUI_BASE_URL, "f-e1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-e1"], "chat-e")

        assert result.ingested == 1
        fields = _extract_form_fields(route.calls[0].request)

        # Should fall back to DEFAULT_KB_ID
        kb_ids = json.loads(fields["kb_ids"])
        assert kb_ids == ["kb-default"]

        # Metadata still forwarded
        meta = json.loads(fields["user_metadata"])
        assert meta == {"project": "Gamma"}


# ──────────────────────────────────────────────────────────────────────
# Scenario F: Multiple files in one webhook → all get same context
# ──────────────────────────────────────────────────────────────────────

class TestScenarioF_MultipleFiles:
    """Multiple files uploaded in one call all receive the same metadata."""

    @respx.mock
    async def test_all_files_get_same_metadata(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        ctx.set_kb_ids("chat-f", ["kb-batch"])
        ctx.apply_directive("chat-f", DirectiveResult(
            action="tag_start",
            metadata={"batch": "2026-04-23"},
        ))

        for fid in ["f-f1", "f-f2", "f-f3"]:
            _mock_download(s.OWUI_BASE_URL, fid, content=f"content-{fid}".encode())

        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(
            ["f-f1", "f-f2", "f-f3"], "chat-f",
        )

        assert result.ingested == 3

        # Verify ALL three requests carry the same metadata
        for i in range(3):
            fields = _extract_form_fields(route.calls[i].request)
            kb_ids = json.loads(fields["kb_ids"])
            meta = json.loads(fields["user_metadata"])
            assert kb_ids == ["kb-batch"], f"Call {i}: wrong kb_ids"
            assert meta == {"batch": "2026-04-23"}, f"Call {i}: wrong metadata"


# ──────────────────────────────────────────────────────────────────────
# Scenario G: Two chats in parallel → isolated contexts
# ──────────────────────────────────────────────────────────────────────

class TestScenarioG_ChatIsolation:
    """Two different chats maintain independent tagging contexts."""

    @respx.mock
    async def test_contexts_are_isolated(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # Chat 1: Active with metadata-A
        ctx.set_kb_ids("chat-g1", ["kb-alpha"])
        ctx.apply_directive("chat-g1", DirectiveResult(
            action="tag_start",
            metadata={"team": "alpha"},
        ))

        # Chat 2: Active with metadata-B
        ctx.set_kb_ids("chat-g2", ["kb-beta"])
        ctx.apply_directive("chat-g2", DirectiveResult(
            action="tag_start",
            metadata={"team": "beta"},
        ))

        _mock_download(s.OWUI_BASE_URL, "f-g1")
        _mock_download(s.OWUI_BASE_URL, "f-g2")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        # Ingest from chat 1
        r1 = await v_stack["orch"].ingest_with_context(["f-g1"], "chat-g1")
        assert r1.ingested == 1

        # Ingest from chat 2
        r2 = await v_stack["orch"].ingest_with_context(["f-g2"], "chat-g2")
        assert r2.ingested == 1

        # Verify chat 1's file got chat 1's metadata
        fields_1 = _extract_form_fields(route.calls[0].request)
        assert json.loads(fields_1["kb_ids"]) == ["kb-alpha"]
        assert json.loads(fields_1["user_metadata"]) == {"team": "alpha"}

        # Verify chat 2's file got chat 2's metadata
        fields_2 = _extract_form_fields(route.calls[1].request)
        assert json.loads(fields_2["kb_ids"]) == ["kb-beta"]
        assert json.loads(fields_2["user_metadata"]) == {"team": "beta"}


# ──────────────────────────────────────────────────────────────────────
# Scenario H: Full directive-parsing → ingestion pipeline
# ──────────────────────────────────────────────────────────────────────

class TestScenarioH_FullPipeline:
    """Simulate raw chat messages being parsed and applied, then verify
    the final Retriva request."""

    @respx.mock
    async def test_raw_message_to_retriva_payload(self, v_stack: dict) -> None:
        s, ctx = v_stack["s"], v_stack["ctx"]

        # Step 1: Parse a raw chat message containing a directive
        raw_message = """@@ingestion_tag_start
project: Artemis
department: R&D
priority: high"""

        directive = parse_directive(raw_message)
        assert directive.action == "tag_start"
        assert directive.metadata == {
            "project": "Artemis",
            "department": "R&D",
            "priority": "high",
        }

        # Step 2: Apply to context (simulates webhook handler)
        ctx.set_kb_ids("chat-h", ["kb-rd-docs"])
        ctx.apply_directive("chat-h", directive)

        # Step 3: Ingest a file
        _mock_download(s.OWUI_BASE_URL, "f-h1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await v_stack["orch"].ingest_with_context(["f-h1"], "chat-h")
        assert result.ingested == 1

        # Step 4: Verify the full Retriva payload
        fields = _extract_form_fields(route.calls[0].request)

        assert fields["source_path"] == "owui:f-h1"
        assert json.loads(fields["kb_ids"]) == ["kb-rd-docs"]
        assert json.loads(fields["user_metadata"]) == {
            "project": "Artemis",
            "department": "R&D",
            "priority": "high",
        }

        # Step 5: Stop tagging, ingest another file
        stop_directive = parse_directive("@@ingestion_tag_stop")
        assert stop_directive.action == "tag_stop"
        ctx.apply_directive("chat-h", stop_directive)

        _mock_download(s.OWUI_BASE_URL, "f-h2")

        result2 = await v_stack["orch"].ingest_with_context(["f-h2"], "chat-h")
        assert result2.ingested == 1

        fields2 = _extract_form_fields(route.calls[1].request)
        assert json.loads(fields2["kb_ids"]) == ["kb-rd-docs"]  # persists
        assert "user_metadata" not in fields2  # cleared by tag_stop
