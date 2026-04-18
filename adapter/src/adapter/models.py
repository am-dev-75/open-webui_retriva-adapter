# SPDX-License-Identifier: MIT
"""Shared data models used across the adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


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


# ---------------------------------------------------------------------------
# Mapping record (mirrors the SQLite row)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MappingRecord:
    """A durable file ↔ document mapping stored in SQLite."""

    id: int | None = None
    owui_file_id: str = ""
    filename: str = ""
    content_hash: str = ""
    retriva_doc_id: str = ""
    status: str = "synced"  # synced | failed | deleting | deleted
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = field(
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
