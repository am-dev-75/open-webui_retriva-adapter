# SPDX-License-Identifier: MIT
"""Durable SQLite mapping store for file ↔ document relationships."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


from adapter.models import MappingRecord

from adapter.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS file_mappings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    owui_file_id   TEXT    NOT NULL UNIQUE,
    filename       TEXT    NOT NULL,
    content_type   TEXT    NOT NULL DEFAULT 'application/octet-stream',
    content_hash   TEXT,
    retriva_doc_id TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'synced',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_owui_file_id ON file_mappings(owui_file_id);
CREATE INDEX IF NOT EXISTS idx_status ON file_mappings(status);
"""


class MappingStore:
    """Async SQLite CRUD for file ↔ document mappings."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle -----------------------------------------------------------

    async def open(self) -> None:
        """Open the database and ensure the schema exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info(f"mapping_store_opened db_path={self._db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("mapping_store_closed")

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MappingStore is not open")
        return self._db

    # -- create --------------------------------------------------------------

    async def create(
        self,
        owui_file_id: str,
        filename: str,
        retriva_doc_id: str,
        content_type: str = "application/octet-stream",
        content_hash: str = "",
        status: str = "synced",
    ) -> MappingRecord:
        """Insert a new mapping. Returns the created record."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            cursor = await self._conn.execute(
                """
                INSERT INTO file_mappings
                    (owui_file_id, filename, content_type, content_hash,
                     retriva_doc_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owui_file_id, filename, content_type, content_hash,
                 retriva_doc_id, status, now, now),
            )
            await self._conn.commit()
            row_id = cursor.lastrowid

        logger.info(f"mapping_created owui_file_id={owui_file_id} retriva_doc_id={retriva_doc_id} status={status}")
        return MappingRecord(
            id=row_id,
            owui_file_id=owui_file_id,
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            retriva_doc_id=retriva_doc_id,
            status=status,
            created_at=now,
            updated_at=now,
        )

    # -- read ----------------------------------------------------------------

    async def get_by_file_id(self, owui_file_id: str) -> MappingRecord | None:
        """Look up a mapping by OWUI file ID."""
        cursor = await self._conn.execute(
            "SELECT * FROM file_mappings WHERE owui_file_id = ?",
            (owui_file_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None

    async def list_all(self, *, status: str | None = None) -> list[MappingRecord]:
        """Return all mappings, optionally filtered by status."""
        if status:
            cursor = await self._conn.execute(
                "SELECT * FROM file_mappings WHERE status = ? ORDER BY created_at",
                (status,),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM file_mappings ORDER BY created_at",
            )
        rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def get_synced_file_ids(self) -> set[str]:
        """Return the set of OWUI file IDs with status 'synced'."""
        cursor = await self._conn.execute(
            "SELECT owui_file_id FROM file_mappings WHERE status = 'synced'",
        )
        rows = await cursor.fetchall()
        return {row["owui_file_id"] for row in rows}

    # -- update --------------------------------------------------------------

    async def update_status(self, owui_file_id: str, status: str) -> None:
        """Update the status of a mapping."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await self._conn.execute(
                """
                UPDATE file_mappings
                SET status = ?, updated_at = ?
                WHERE owui_file_id = ?
                """,
                (status, now, owui_file_id),
            )
            await self._conn.commit()
        logger.info(f"mapping_status_updated owui_file_id={owui_file_id} status={status}")

    # -- delete --------------------------------------------------------------

    async def prune_deleted(self) -> int:
        """Remove all rows with status 'deleted'. Returns count removed."""
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM file_mappings WHERE status = 'deleted'",
            )
            await self._conn.commit()
            count = cursor.rowcount
        if count:
            logger.info(f"mappings_pruned count={count}")
        return count

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: aiosqlite.Row) -> MappingRecord:
        return MappingRecord(
            id=row["id"],
            owui_file_id=row["owui_file_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            content_hash=row["content_hash"] or "",
            retriva_doc_id=row["retriva_doc_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
