# SPDX-License-Identifier: MIT
"""Chat observer — polls Open WebUI chat API to discover new user messages.

Mirrors the :class:`~adapter.observer.FileObserver` pattern: periodically
polls the OWUI chat list, detects chats with new activity, fetches full
chat details, and extracts new user-role messages for directive parsing.

State tracking is ephemeral (in-memory):
    - ``_chat_updated_at``  — last ``updated_at`` per chat
    - ``_processed_msg_ids`` — set of processed message IDs per chat

On adapter restart the state resets, causing a one-time re-scan of recent
messages.  This is safe because :class:`~adapter.ingestion_context.IngestionContext`
is also ephemeral — both subsystems converge to the same initial state.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from adapter.config import Settings
from adapter.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single user message discovered by the chat observer."""

    chat_id: str
    message_id: str
    content: str


class ChatObserver:
    """Polls Open WebUI ``/api/chats`` to discover new user messages."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = settings.OWUI_BASE_URL.rstrip("/")
        self._api_key = settings.OWUI_API_KEY
        self._client = client

        # Ephemeral per-chat state (lost on restart)
        self._chat_updated_at: dict[str, float] = {}
        self._processed_msg_ids: dict[str, set[str]] = {}

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def poll_new_messages(self) -> list[ChatMessage]:
        """Poll OWUI for new user messages across all active chats.

        Returns a list of :class:`ChatMessage` instances for messages
        that have not been processed yet (by message ID tracking).
        """
        try:
            chats = await self._list_chats()
        except Exception as exc:
            logger.error(f"chat_list_failed error={exc}")
            return []

        new_messages: list[ChatMessage] = []

        for chat_summary in chats:
            chat_id = chat_summary.get("id", "")
            if not chat_id:
                continue

            updated_at = chat_summary.get("updated_at", 0)

            # Skip if this chat has not been updated since last poll
            if chat_id in self._chat_updated_at:
                if updated_at <= self._chat_updated_at[chat_id]:
                    continue

            # Fetch full chat to get messages
            try:
                messages = await self._get_chat_messages(chat_id)
            except Exception as exc:
                logger.error(
                    f"chat_messages_fetch_failed chat_id={chat_id} error={exc}"
                )
                continue

            # Filter for new user-role messages
            seen = self._processed_msg_ids.get(chat_id, set())
            for msg in messages:
                msg_id = msg.get("id", "")
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "user" and msg_id and msg_id not in seen:
                    new_messages.append(
                        ChatMessage(
                            chat_id=chat_id,
                            message_id=msg_id,
                            content=content,
                        )
                    )
                    seen.add(msg_id)

            self._processed_msg_ids[chat_id] = seen
            self._chat_updated_at[chat_id] = updated_at

        if new_messages:
            logger.info(
                f"chat_messages_discovered count={len(new_messages)} "
                f"chats={len({m.chat_id for m in new_messages})}"
            )
        else:
            logger.debug("chat_poll_complete no_new_messages")

        return new_messages

    # ------------------------------------------------------------------
    # OWUI API calls
    # ------------------------------------------------------------------

    async def _list_chats(self) -> list[dict]:
        """Fetch the chat list from Open WebUI.

        Returns a list of chat summary dicts with at least ``id`` and
        ``updated_at`` fields.
        """
        url = f"{self._base_url}/api/v1/chats/"
        response = await self._client.get(url, headers=self._auth_headers())
        response.raise_for_status()

        # Guard: OWUI returns HTML for invalid API paths
        ct = response.headers.get("content-type", "")
        if "application/json" not in ct:
            logger.warning(
                f"chat_list_unexpected_content_type content_type={ct!r} "
                f"url={url} (expected application/json)"
            )
            return []

        raw = response.json()

        # OWUI may return a list directly or a paginated dict
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            if "data" in raw:
                return raw["data"]
            if "items" in raw:
                return raw["items"]
        return []

    async def _get_chat_messages(self, chat_id: str) -> list[dict]:
        """Fetch the full message list for a single chat.

        Returns a list of message dicts with ``id``, ``role``, ``content``.
        """
        url = f"{self._base_url}/api/v1/chats/{chat_id}"
        response = await self._client.get(url, headers=self._auth_headers())
        response.raise_for_status()

        # Guard: OWUI returns HTML for invalid API paths
        ct = response.headers.get("content-type", "")
        if "application/json" not in ct:
            logger.warning(
                f"chat_detail_unexpected_content_type content_type={ct!r} "
                f"chat_id={chat_id}"
            )
            return []

        raw = response.json()

        # The chat object contains a "chat" sub-object with "messages"
        chat_data = raw.get("chat", raw)
        messages = chat_data.get("messages", [])

        if isinstance(messages, list):
            return messages
        return []
