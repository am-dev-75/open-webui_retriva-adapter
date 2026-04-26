# SPDX-License-Identifier: MIT
"""Tests for the ChatObserver — polls OWUI chat API for new user messages.

Validates:
- New user messages are detected and returned
- Unchanged chats are skipped (updated_at comparison)
- Only user-role messages are extracted (assistant messages ignored)
- Processed message IDs are tracked — no re-emission on second poll
- API errors are handled gracefully (logged, not raised)
- Empty chat list returns empty results
"""

from __future__ import annotations

import httpx
import pytest
import respx

from adapter.chat_observer import ChatMessage, ChatObserver
from adapter.config import Settings


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def chat_settings(tmp_path) -> Settings:
    return Settings(
        OWUI_BASE_URL="http://owui:3000",
        OWUI_API_KEY="test-key",
        RETRIVA_INGESTION_API_HOST="retriva",
        RETRIVA_INGESTION_PORT=8400,
        DB_PATH=tmp_path / "chat_obs.db",
        POLL_INTERVAL_SECONDS=5,
    )


@pytest.fixture
def chat_observer(chat_settings: Settings) -> ChatObserver:
    """Create a ChatObserver with a real httpx.AsyncClient (mocked via respx)."""
    client = httpx.AsyncClient()
    return ChatObserver(chat_settings, client)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_chat_summary(chat_id: str, updated_at: float = 1.0) -> dict:
    return {
        "id": chat_id,
        "title": f"Chat {chat_id}",
        "updated_at": updated_at,
    }


def _make_chat_detail(chat_id: str, messages: list[dict]) -> dict:
    """Build a chat detail response matching OWUI's format."""
    return {
        "id": chat_id,
        "chat": {
            "messages": messages,
        },
    }


def _make_message(msg_id: str, role: str, content: str) -> dict:
    return {"id": msg_id, "role": role, "content": content}


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

class TestNewMessageDetection:
    """Verify that new user messages are discovered and returned."""

    @respx.mock
    async def test_new_user_message_detected(self, chat_observer: ChatObserver) -> None:
        """A single new user message is discovered on first poll."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "Hello world"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 1
        assert messages[0] == ChatMessage(
            chat_id="chat-1", message_id="m1", content="Hello world",
        )

    @respx.mock
    async def test_multiple_new_messages_across_chats(
        self, chat_observer: ChatObserver,
    ) -> None:
        """Messages from multiple chats are all returned."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
                _make_chat_summary("chat-2", updated_at=200.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "msg-1"),
            ])),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-2").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-2", [
                _make_message("m2", "user", "msg-2"),
                _make_message("m3", "user", "msg-3"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 3
        chat_ids = {m.chat_id for m in messages}
        assert chat_ids == {"chat-1", "chat-2"}


class TestUnchangedChatSkipped:
    """Verify that chats with unchanged updated_at are not re-fetched."""

    @respx.mock
    async def test_second_poll_skips_unchanged_chat(
        self, chat_observer: ChatObserver,
    ) -> None:
        """Second poll with same updated_at skips the chat entirely."""
        chat_list = [_make_chat_summary("chat-1", updated_at=100.0)]

        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=chat_list),
        )
        chat_detail_route = respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "hello"),
            ])),
        )

        # First poll — fetches detail
        msgs1 = await chat_observer.poll_new_messages()
        assert len(msgs1) == 1
        assert chat_detail_route.call_count == 1

        # Second poll — same updated_at → skip
        msgs2 = await chat_observer.poll_new_messages()
        assert len(msgs2) == 0
        assert chat_detail_route.call_count == 1  # NOT called again

    @respx.mock
    async def test_updated_chat_is_refetched(
        self, chat_observer: ChatObserver,
    ) -> None:
        """When updated_at changes, the chat is re-fetched."""
        chat_list_route = respx.get("http://owui:3000/api/v1/chats/")
        chat_detail_route = respx.get("http://owui:3000/api/v1/chats/chat-1")

        # First poll
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "hello"),
            ])),
        )
        msgs1 = await chat_observer.poll_new_messages()
        assert len(msgs1) == 1

        # Second poll — updated_at changed, new message added
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=200.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "hello"),
                _make_message("m2", "user", "@@ingestion_tag_start\nproject: Apollo"),
            ])),
        )
        msgs2 = await chat_observer.poll_new_messages()

        # Only the NEW message (m2) should be returned
        assert len(msgs2) == 1
        assert msgs2[0].message_id == "m2"


class TestOnlyUserMessagesExtracted:
    """Verify that only messages with role='user' are returned."""

    @respx.mock
    async def test_assistant_messages_ignored(
        self, chat_observer: ChatObserver,
    ) -> None:
        """Messages with role='assistant' are not returned."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "question"),
                _make_message("m2", "assistant", "answer"),
                _make_message("m3", "system", "system prompt"),
                _make_message("m4", "user", "follow-up"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 2
        assert all(m.message_id in {"m1", "m4"} for m in messages)


class TestProcessedMessagesNotReemitted:
    """Verify that already-processed message IDs are not re-emitted."""

    @respx.mock
    async def test_processed_ids_tracked(
        self, chat_observer: ChatObserver,
    ) -> None:
        """Messages already returned once are never returned again."""
        chat_list_route = respx.get("http://owui:3000/api/v1/chats/")
        chat_detail_route = respx.get("http://owui:3000/api/v1/chats/chat-1")

        # First poll
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "hello"),
            ])),
        )
        msgs1 = await chat_observer.poll_new_messages()
        assert len(msgs1) == 1
        assert msgs1[0].message_id == "m1"

        # Second poll — chat updated but same message still there
        chat_list_route.mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=200.0),
            ]),
        )
        chat_detail_route.mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "hello"),  # already seen
                _make_message("m2", "user", "new message"),  # new
            ])),
        )
        msgs2 = await chat_observer.poll_new_messages()

        assert len(msgs2) == 1
        assert msgs2[0].message_id == "m2"


class TestAPIErrorTolerance:
    """Verify that API errors are handled gracefully."""

    @respx.mock
    async def test_chat_list_error_returns_empty(
        self, chat_observer: ChatObserver,
    ) -> None:
        """HTTP error on chat list → empty result, no crash."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(500, json={"error": "internal"}),
        )

        messages = await chat_observer.poll_new_messages()

        assert messages == []

    @respx.mock
    async def test_chat_detail_error_skips_chat(
        self, chat_observer: ChatObserver,
    ) -> None:
        """HTTP error on single chat detail → that chat is skipped, others proceed."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-bad", updated_at=100.0),
                _make_chat_summary("chat-good", updated_at=100.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-bad").mock(
            return_value=httpx.Response(404, json={"error": "not found"}),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-good").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-good", [
                _make_message("m1", "user", "works"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 1
        assert messages[0].chat_id == "chat-good"


class TestEmptyChatList:
    """Verify behaviour with an empty chat list."""

    @respx.mock
    async def test_empty_list_returns_empty(
        self, chat_observer: ChatObserver,
    ) -> None:
        """No chats → no messages."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[]),
        )

        messages = await chat_observer.poll_new_messages()

        assert messages == []

    @respx.mock
    async def test_paginated_response_handled(
        self, chat_observer: ChatObserver,
    ) -> None:
        """OWUI may return paginated dict with 'data' key."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json={
                "data": [_make_chat_summary("chat-1", updated_at=100.0)],
            }),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "via paginated"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 1
        assert messages[0].content == "via paginated"


class TestDirectiveMessageContent:
    """Verify that directive messages are returned with full content preserved."""

    @respx.mock
    async def test_directive_content_preserved(
        self, chat_observer: ChatObserver,
    ) -> None:
        """Full message text including key:value lines is returned intact."""
        directive_msg = "@@ingestion_tag_start\nproject: Apollo\nmilestone: M4"

        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", directive_msg),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 1
        assert messages[0].content == directive_msg

    @respx.mock
    async def test_stop_directive_content(
        self, chat_observer: ChatObserver,
    ) -> None:
        """@@ingestion_tag_stop message is returned with exact content."""
        respx.get("http://owui:3000/api/v1/chats/").mock(
            return_value=httpx.Response(200, json=[
                _make_chat_summary("chat-1", updated_at=100.0),
            ]),
        )
        respx.get("http://owui:3000/api/v1/chats/chat-1").mock(
            return_value=httpx.Response(200, json=_make_chat_detail("chat-1", [
                _make_message("m1", "user", "@@ingestion_tag_stop"),
            ])),
        )

        messages = await chat_observer.poll_new_messages()

        assert len(messages) == 1
        assert messages[0].content == "@@ingestion_tag_stop"
