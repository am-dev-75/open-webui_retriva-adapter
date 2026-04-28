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

"""Tests for the chat message webhook endpoint and contextual ingestion.

Validates:
- Directive parsing via webhook
- KB ID propagation
- Metadata forwarding to Retriva
- Debug endpoint gating
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from adapter.config import Settings
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.mapping_store import MappingStore
from adapter.observer import FileObserver
from adapter.orchestrator import SyncOrchestrator
from adapter.retriva_client import RetrivaClient


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def webhook_settings(tmp_path: Path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_INGESTION_API_HOST="retriva",
        RETRIVA_INGESTION_PORT=8400,
        DB_PATH=tmp_path / "webhook.db",
        POLL_INTERVAL_SECONDS=5,
        DEFAULT_KB_ID="default-kb",
    )


@pytest.fixture
async def webhook_stack(webhook_settings: Settings):
    """Build a fully wired stack for webhook testing."""
    store = MappingStore(webhook_settings.DB_PATH)
    await store.open()

    ingestion_ctx = IngestionContext(
        default_kb_id=webhook_settings.DEFAULT_KB_ID,
    )

    async with httpx.AsyncClient() as client:
        observer = FileObserver(webhook_settings, client)
        fetcher = FileFetcher(webhook_settings, client)
        retriva = RetrivaClient(webhook_settings, client)
        orchestrator = SyncOrchestrator(
            observer, fetcher, retriva, store,
            ingestion_context=ingestion_ctx,
        )

        yield {
            "settings": webhook_settings,
            "store": store,
            "orchestrator": orchestrator,
            "ingestion_ctx": ingestion_ctx,
            "retriva": retriva,
        }

    await store.close()


# ──────────────────────────────────────────────────────────────────────
# Contextual ingestion tests
# ──────────────────────────────────────────────────────────────────────

class TestContextualIngestion:
    """End-to-end: directive → upload → verify metadata forwarded."""

    @respx.mock
    async def test_ingest_with_metadata(self, webhook_stack: dict) -> None:
        """Files ingested via webhook carry user_metadata and kb_ids."""
        s = webhook_stack["settings"]
        ctx = webhook_stack["ingestion_ctx"]
        orch = webhook_stack["orchestrator"]

        # 1. Set up context: activate tagging with metadata + KB IDs
        from adapter.directive_parser import DirectiveResult

        ctx.set_kb_ids("chat-1", ["kb-research"])
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start",
            metadata={"project": "Apollo", "milestone": "M4"},
        ))

        # 2. Mock OWUI file download
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f-doc/content").mock(
            return_value=httpx.Response(
                200,
                content=b"document content",
                headers={"content-type": "text/plain"},
            ),
        )

        # 3. Mock Retriva ingest — capture the request
        ingest_route = respx.post(
            f"{s.retriva_ingestion_url}/api/v1/ingest/text",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok", "job_id": "j-ctx"},
            ),
        )

        # 4. Ingest with context
        result = await orch.ingest_with_context(["f-doc"], "chat-1")

        assert result.ingested == 1
        assert result.failed == 0

        # 5. Verify the Retriva request included metadata
        assert ingest_route.called
        request = ingest_route.calls[0].request
        body = request.content.decode("utf-8", errors="replace")

        # The form data should contain kb_ids and user_metadata
        assert "kb_ids" in body
        assert "user_metadata" in body
        assert "Apollo" in body
        assert "kb-research" in body

        # 6. Verify mapping stored
        mapping = await webhook_stack["store"].get_by_file_id("f-doc")
        assert mapping is not None
        assert mapping.status == "synced"

    @respx.mock
    async def test_ingest_without_context_uses_defaults(
        self, webhook_stack: dict,
    ) -> None:
        """When no tagging is active, kb_ids defaults but no user_metadata."""
        s = webhook_stack["settings"]
        orch = webhook_stack["orchestrator"]

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f-plain/content").mock(
            return_value=httpx.Response(
                200, content=b"plain content",
                headers={"content-type": "text/plain"},
            ),
        )

        ingest_route = respx.post(
            f"{s.retriva_ingestion_url}/api/v1/ingest/text",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok"},
            ),
        )

        result = await orch.ingest_with_context(["f-plain"], "chat-no-tags")

        assert result.ingested == 1

        # Default KB should be used
        request = ingest_route.calls[0].request
        body = request.content.decode("utf-8", errors="replace")
        assert "default-kb" in body

    @respx.mock
    async def test_ingest_skips_already_synced(self, webhook_stack: dict) -> None:
        """Files already synced should be skipped."""
        store = webhook_stack["store"]
        orch = webhook_stack["orchestrator"]

        await store.create("f-exists", "exists.txt", "d-exists", status="synced")

        result = await orch.ingest_with_context(["f-exists"], "chat-1")

        assert result.skipped == 1
        assert result.ingested == 0

    @respx.mock
    async def test_metadata_replacement_reflected_in_ingestion(
        self, webhook_stack: dict,
    ) -> None:
        """Second tag_start replaces metadata — new ingestion uses new metadata."""
        s = webhook_stack["settings"]
        ctx = webhook_stack["ingestion_ctx"]
        orch = webhook_stack["orchestrator"]

        from adapter.directive_parser import DirectiveResult

        # First directive
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start",
            metadata={"project": "Alpha", "phase": "1"},
        ))

        # Second directive — full replacement
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start",
            metadata={"project": "Beta"},
        ))

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/files/f-replaced/content").mock(
            return_value=httpx.Response(
                200, content=b"content",
                headers={"content-type": "text/plain"},
            ),
        )

        ingest_route = respx.post(
            f"{s.retriva_ingestion_url}/api/v1/ingest/text",
        ).mock(
            return_value=httpx.Response(
                202, json={"status": "accepted", "message": "ok"},
            ),
        )

        result = await orch.ingest_with_context(["f-replaced"], "chat-1")
        assert result.ingested == 1

        body = ingest_route.calls[0].request.content.decode("utf-8", errors="replace")
        assert "Beta" in body
        # "Alpha" and "phase" should NOT be present (replacement, not merge)
        assert "Alpha" not in body
        assert "phase" not in body


# ──────────────────────────────────────────────────────────────────────
# Ingestion context debug info
# ──────────────────────────────────────────────────────────────────────

class TestIngestionContextDebugInfo:
    """Tests for the debug endpoint data (context layer, not HTTP)."""

    def test_debug_info_after_activation(self) -> None:
        from adapter.directive_parser import DirectiveResult

        ctx = IngestionContext(default_kb_id="dflt")
        ctx.set_kb_ids("c1", ["kb-1"])
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"project": "Z"},
        ))

        info = ctx.get_debug_info("c1")
        assert info["state"] == "ACTIVE"
        assert info["user_metadata"] == {"project": "Z"}
        assert info["kb_ids"] == ["kb-1"]

    def test_debug_info_after_deactivation(self) -> None:
        from adapter.directive_parser import DirectiveResult

        ctx = IngestionContext()
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"x": "y"},
        ))
        ctx.apply_directive("c1", DirectiveResult(action="tag_stop"))

        info = ctx.get_debug_info("c1")
        assert info["state"] == "INACTIVE"
        assert info["user_metadata"] == {}