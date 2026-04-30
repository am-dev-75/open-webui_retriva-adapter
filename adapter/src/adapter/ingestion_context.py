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

"""Per-chat ingestion context — ephemeral state machine for metadata tagging.

State machine
-------------
* ``INACTIVE`` → ``@@ingestion_tag_start`` → ``ACTIVE`` (metadata stored)
* ``ACTIVE``   → ``@@ingestion_tag_start`` → ``ACTIVE`` (metadata **replaced**)
* ``ACTIVE``   → ``@@ingestion_tag_stop``  → ``INACTIVE`` (metadata cleared)

Design decisions
----------------
* ``kb_ids`` are tracked **independently** of metadata state.
* State is held in memory — intentionally lost on restart.
* Thread safety via :class:`threading.Lock` (lightweight; async contention
  is negligible for dict lookups).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from adapter.directive_parser import DirectiveResult

from adapter.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class _ChatContext:
    """Internal per-chat state."""

    state: Literal["ACTIVE", "INACTIVE"] = "INACTIVE"
    user_metadata: dict[str, str] = field(default_factory=dict)
    kb_ids: list[str] = field(default_factory=list)
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class IngestionContext:
    """Thread-safe, in-memory per-chat ingestion context."""

    def __init__(self, default_kb_id: str = "") -> None:
        self._lock = threading.Lock()
        self._chats: dict[str, _ChatContext] = {}
        self._default_kb_id = default_kb_id

    # ------------------------------------------------------------------
    # Directive application
    # ------------------------------------------------------------------

    def apply_directive(self, chat_id: str, directive: DirectiveResult) -> None:
        """Apply a parsed directive to the chat's ingestion context.

        * ``tag_start`` → activate and **replace** metadata entirely.
        * ``tag_stop``  → deactivate and clear metadata.
        * ``none``      → no-op.
        """
        if directive.action == "none":
            return

        with self._lock:
            ctx = self._chats.setdefault(chat_id, _ChatContext())
            now = datetime.now(timezone.utc).isoformat()

            if directive.action == "tag_start":
                ctx.state = "ACTIVE"
                ctx.user_metadata = dict(directive.metadata)  # full replace
                ctx.last_updated = now
                logger.debug(f"DEBUG: IngestionContext ACTIVE chat_id={chat_id} metadata={ctx.user_metadata!r}")
                logger.info(
                    f"ingestion_context_activated chat_id={chat_id} "
                    f"metadata_keys={list(directive.metadata.keys())}"
                )

            elif directive.action == "tag_stop":
                ctx.state = "INACTIVE"
                ctx.user_metadata = {}
                ctx.last_updated = now
                logger.info(f"ingestion_context_deactivated chat_id={chat_id}")

    # ------------------------------------------------------------------
    # KB IDs (independent of metadata state)
    # ------------------------------------------------------------------

    def set_kb_ids(self, chat_id: str, kb_ids: list[str]) -> None:
        """Set the Knowledge Base IDs for a chat session."""
        with self._lock:
            ctx = self._chats.setdefault(chat_id, _ChatContext())
            ctx.kb_ids = list(kb_ids)
            ctx.last_updated = datetime.now(timezone.utc).isoformat()

    def get_kb_ids(self, chat_id: str) -> list[str]:
        """Return the KB IDs for a chat, falling back to the default KB."""
        with self._lock:
            ctx = self._chats.get(chat_id)
            if ctx and ctx.kb_ids:
                return list(ctx.kb_ids)
        # Fallback to default KB
        if self._default_kb_id:
            return [self._default_kb_id]
        return []

    # ------------------------------------------------------------------
    # Metadata queries
    # ------------------------------------------------------------------

    def is_active(self, chat_id: str) -> bool:
        """Return whether tagging is active for the chat."""
        with self._lock:
            ctx = self._chats.get(chat_id)
            return ctx is not None and ctx.state == "ACTIVE"

    def get_metadata(self, chat_id: str) -> dict[str, str] | None:
        """Return the active metadata dict, or ``None`` if inactive."""
        with self._lock:
            ctx = self._chats.get(chat_id)
            if ctx and ctx.state == "ACTIVE":
                return dict(ctx.user_metadata)
        return None

    def get_ingestion_payload(self, chat_id: str | None) -> dict:
        """Build the combined ingestion payload for a chat.

        If chat_id is None, it attempts to find the most recently updated
        active metadata context as a global fallback.
        """
        if chat_id is None:
            kb_ids = [self._default_kb_id] if self._default_kb_id else []
            metadata = self.get_recent_active_metadata() or {}
        else:
            kb_ids = self.get_kb_ids(chat_id)
            metadata = self.get_metadata(chat_id) or {}

        return {
            "kb_ids": kb_ids,
            "user_metadata": metadata,
        }

    def get_recent_active_metadata(self) -> dict[str, str] | None:
        """Find the metadata of the most recently updated ACTIVE chat."""
        with self._lock:
            active_chats = [
                (c.last_updated, c.user_metadata)
                for c in self._chats.values()
                if c.state == "ACTIVE" and c.user_metadata
            ]
            if not active_chats:
                return None
            
            # Sort by last_updated descending
            active_chats.sort(key=lambda x: x[0], reverse=True)
            return dict(active_chats[0][1])

    # ------------------------------------------------------------------
    # Debug / introspection
    # ------------------------------------------------------------------

    def get_debug_info(self, chat_id: str) -> dict | None:
        """Return full context state for the debug endpoint.

        Returns ``None`` if no context exists for the chat.
        """
        with self._lock:
            ctx = self._chats.get(chat_id)
            if ctx is None:
                return None
            return {
                "chat_id": chat_id,
                "state": ctx.state,
                "user_metadata": dict(ctx.user_metadata),
                "kb_ids": list(ctx.kb_ids),
                "last_updated": ctx.last_updated,
            }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clear(self, chat_id: str) -> None:
        """Remove all state for a chat."""
        with self._lock:
            self._chats.pop(chat_id, None)
        logger.info(f"ingestion_context_cleared chat_id={chat_id}")