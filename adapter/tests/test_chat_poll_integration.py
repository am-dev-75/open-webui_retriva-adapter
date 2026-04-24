# SPDX-License-Identifier: MIT
"""Integration tests — chat-poll → directive → context → ingestion flow.

Validates the full pipeline: ChatObserver discovers a directive message,
the directive parser extracts it, the IngestionContext is updated, and
subsequent file ingestion carries the correct user_metadata and kb_ids.

Scenarios:
  1. Directive in chat → context activated
  2. File uploaded after directive → metadata attached
  3. tag_stop deactivates context
  4. Multiple chats isolated
  5. Non-directive messages ignored
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from adapter.chat_observer import ChatObserver
from adapter.config import Settings
from adapter.directive_parser import parse_directive
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.mapping_store import MappingStore
from adapter.observer import FileObserver
from adapter.orchestrator import SyncOrchestrator
from adapter.retriva_client import RetrivaClient
from adapter import metrics


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _extract_form_fields(request: httpx.Request) -> dict[str, str]:
    """Extract form-data field values from a multipart request body."""
    body = request.content
    content_type = request.headers.get("content-type", "")

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

        name_start = decoded.index('name="') + 6
        name_end = decoded.index('"', name_start)
        name = decoded[name_start:name_end]

        if "filename=" in decoded.split("\r\n\r\n")[0]:
            continue

        if "\r\n\r\n" in decoded:
            value = decoded.split("\r\n\r\n", 1)[1].rstrip("\r\n-")
            fields[name] = value

    return fields


def _make_chat_summary(chat_id: str, updated_at: float = 1.0) -> dict:
    return {"id": chat_id, "title": f"Chat {chat_id}", "updated_at": updated_at}


def _make_chat_detail(chat_id: str, messages: list[dict]) -> dict:
    return {"id": chat_id, "chat": {"messages": messages}}


def _make_message(msg_id: str, role: str, content: str) -> dict:
    return {"id": msg_id, "role": role, "content": content}


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def cp_settings(tmp_path: Path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_BASE_URL="http://retriva:8400",
        DB_PATH=tmp_path / "chatpoll_integ.db",
        POLL_INTERVAL_SECONDS=5,
        DEFAULT_KB_ID="kb-default",
    )


@pytest.fixture
async def cp_stack(cp_settings: Settings):
    """Build a fully wired stack including ChatObserver."""
    store = MappingStore(cp_settings.DB_PATH)
    await store.open()

    ctx = IngestionContext(default_kb_id=cp_settings.DEFAULT_KB_ID)

    async with httpx.AsyncClient() as client:
        chat_observer = ChatObserver(cp_settings, client)
        observer = FileObserver(cp_settings, client)
        fetcher = FileFetcher(cp_settings, client)
        retriva = RetrivaClient(cp_settings, client)
        orchestrator = SyncOrchestrator(
            observer, fetcher, retriva, store,
            ingestion_context=ctx,
        )

        yield {
            "s": cp_settings,
            "store": store,
            "ctx": ctx,
            "chat_obs": chat_observer,
            "orch": orchestrator,
        }

    await store.close()


async def _simulate_chat_poll(
    chat_obs: ChatObserver,
    ctx: IngestionContext,
) -> None:
    """Simulate what _run_chat_poll does in main.py."""
    new_messages = await chat_obs.poll_new_messages()
    for msg in new_messages:
        directive = parse_directive(msg.content)
        if directive.action != "none":
            ctx.apply_directive(msg.chat_id, directive)


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
            202, json={"status": "accepted", "message": "ok", "job_id": "j-cp"},
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Scenario 1: Directive in chat → context activated
# ──────────────────────────────────────────────────────────────────────

class TestDirectiveActivatesContext:
    """Chat poll discovers @@ingestion_tag_start → context becomes ACTIVE."""

    @respx.mock
    async def test_tag_start_activates_context(self, cp_stack: dict) -> None:
        s, ctx, chat_obs = cp_stack["s"], cp_stack["ctx"], cp_stack["chat_obs"]

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "@@ingestion_tag_start\nproject: Apollo\nmilestone: M4"),
            ])),
        )

        await _simulate_chat_poll(chat_obs, ctx)

        assert ctx.is_active("chat-1") is True
        assert ctx.get_metadata("chat-1") == {"project": "Apollo", "milestone": "M4"}


# ──────────────────────────────────────────────────────────────────────
# Scenario 2: File uploaded after directive → metadata attached
# ──────────────────────────────────────────────────────────────────────

class TestFileIngestedWithMetadata:
    """After chat poll activates tagging, file ingestion carries metadata."""

    @respx.mock
    async def test_file_carries_metadata_after_directive(
        self, cp_stack: dict,
    ) -> None:
        s, ctx, chat_obs, orch = (
            cp_stack["s"], cp_stack["ctx"],
            cp_stack["chat_obs"], cp_stack["orch"],
        )

        # Step 1: Chat poll discovers directive
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "@@ingestion_tag_start\nproject: Artemis\ndept: R&D"),
            ])),
        )

        await _simulate_chat_poll(chat_obs, ctx)
        assert ctx.is_active("chat-1") is True

        # Step 2: File upload + ingestion with context
        _mock_download(s.OWUI_BASE_URL, "f-1")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await orch.ingest_with_context(["f-1"], "chat-1")

        assert result.ingested == 1
        fields = _extract_form_fields(route.calls[0].request)

        # Verify metadata was forwarded
        meta = json.loads(fields["user_metadata"])
        assert meta == {"project": "Artemis", "dept": "R&D"}

        # Verify default KB fallback
        kb_ids = json.loads(fields["kb_ids"])
        assert kb_ids == ["kb-default"]


# ──────────────────────────────────────────────────────────────────────
# Scenario 3: tag_stop deactivates context
# ──────────────────────────────────────────────────────────────────────

class TestTagStopDeactivates:
    """@@ingestion_tag_stop clears metadata — subsequent upload has none."""

    @respx.mock
    async def test_tag_stop_clears_context(self, cp_stack: dict) -> None:
        s, ctx, chat_obs, orch = (
            cp_stack["s"], cp_stack["ctx"],
            cp_stack["chat_obs"], cp_stack["orch"],
        )

        chat_list_route = respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/")
        chat_detail_route = respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-1")

        # Poll 1: tag_start
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "@@ingestion_tag_start\nenv: staging"),
            ])),
        )
        await _simulate_chat_poll(chat_obs, ctx)
        assert ctx.is_active("chat-1") is True

        # Poll 2: tag_stop (chat updated, new message)
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=200.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "@@ingestion_tag_start\nenv: staging"),
                _make_message("m2", "assistant", "Tags activated."),
                _make_message("m3", "user", "@@ingestion_tag_stop"),
            ])),
        )
        await _simulate_chat_poll(chat_obs, ctx)
        assert ctx.is_active("chat-1") is False

        # File uploaded after tag_stop → no user_metadata
        _mock_download(s.OWUI_BASE_URL, "f-nostop")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        result = await orch.ingest_with_context(["f-nostop"], "chat-1")
        assert result.ingested == 1

        fields = _extract_form_fields(route.calls[0].request)
        assert "user_metadata" not in fields


# ──────────────────────────────────────────────────────────────────────
# Scenario 4: Multiple chats isolated
# ──────────────────────────────────────────────────────────────────────

class TestChatIsolation:
    """Directives in chat-1 do not affect chat-2."""

    @respx.mock
    async def test_contexts_are_isolated(self, cp_stack: dict) -> None:
        s, ctx, chat_obs, orch = (
            cp_stack["s"], cp_stack["ctx"],
            cp_stack["chat_obs"], cp_stack["orch"],
        )

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-a", updated_at=100.0),
                _make_chat_summary("chat-b", updated_at=100.0),
            ]),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-a").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-a", [
                _make_message("ma1", "user", "@@ingestion_tag_start\nteam: alpha"),
            ])),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-b").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-b", [
                _make_message("mb1", "user", "@@ingestion_tag_start\nteam: beta"),
            ])),
        )

        await _simulate_chat_poll(chat_obs, ctx)

        assert ctx.is_active("chat-a") is True
        assert ctx.is_active("chat-b") is True
        assert ctx.get_metadata("chat-a") == {"team": "alpha"}
        assert ctx.get_metadata("chat-b") == {"team": "beta"}

        # Ingest from each chat
        _mock_download(s.OWUI_BASE_URL, "f-a")
        _mock_download(s.OWUI_BASE_URL, "f-b")
        route = _mock_ingest(s.RETRIVA_BASE_URL)

        await orch.ingest_with_context(["f-a"], "chat-a")
        await orch.ingest_with_context(["f-b"], "chat-b")

        fields_a = _extract_form_fields(route.calls[0].request)
        fields_b = _extract_form_fields(route.calls[1].request)

        assert json.loads(fields_a["user_metadata"]) == {"team": "alpha"}
        assert json.loads(fields_b["user_metadata"]) == {"team": "beta"}


# ──────────────────────────────────────────────────────────────────────
# Scenario 5: Non-directive messages ignored
# ──────────────────────────────────────────────────────────────────────

class TestNonDirectiveIgnored:
    """Regular chat messages do not alter the ingestion context."""

    @respx.mock
    async def test_regular_message_no_context_change(
        self, cp_stack: dict,
    ) -> None:
        s, ctx, chat_obs = cp_stack["s"], cp_stack["ctx"], cp_stack["chat_obs"]

        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get(f"{s.OWUI_BASE_URL}/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "What is the status of Project Apollo?"),
                _make_message("m2", "user", "Can you summarize the report?"),
            ])),
        )

        await _simulate_chat_poll(chat_obs, ctx)

        # Context should remain INACTIVE (no directive detected)
        assert ctx.is_active("chat-1") is False
        assert ctx.get_metadata("chat-1") is None
