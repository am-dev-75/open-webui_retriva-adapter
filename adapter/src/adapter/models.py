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

"""Shared data models used across the adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Open WebUI file representation (subset of the OWUI response)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OWUIFile:
    """A file record as returned by ``GET /api/v1/files``."""

    id: str
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0
    hash: str = ""
    created_at: int = 0  # OWUI epoch-ms timestamp


# ---------------------------------------------------------------------------
# Downloaded file content
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FetchedFile:
    """Raw file bytes fetched from Open WebUI."""

    file_id: str
    filename: str
    content_type: str
    content: bytes
    size: int
    kb_ids: tuple[str, ...] = ()
    user_metadata: tuple[tuple[str, str], ...] = ()

    def metadata_dict(self) -> dict[str, str]:
        """Return user_metadata as a plain dict."""
        return dict(self.user_metadata)


# ---------------------------------------------------------------------------
# Mapping record (mirrors the SQLite row)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MappingRecord:
    """A durable file ↔ document mapping stored in SQLite."""

    id: int | None = None
    owui_file_id: str = ""
    filename: str = ""
    content_type: str = "application/octet-stream"
    content_hash: str = ""
    retriva_doc_id: str = ""
    status: str = "synced"  # synced | failed | deleting | deleted
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

@dataclass(slots=True)
class KBMappingRecord:
    """A durable Knowledge Base mapping stored in SQLite."""

    owui_kb_id: str = ""
    retriva_kb_id: str = ""
    last_seen_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )



# ---------------------------------------------------------------------------
# Sync result summary
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SyncResult:
    """Summary of a single sync cycle."""

    ingested: int = 0
    deleted: int = 0
    failed: int = 0
    retried: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chat webhook payload
# ---------------------------------------------------------------------------

class ChatMessagePayload(BaseModel):
    """Payload received from Open WebUI via the chat message webhook."""

    chat_id: str
    message: str
    kb_ids: list[str] = []
    file_ids: list[str] = []