# SPDX-License-Identifier: MIT
"""Sync orchestrator — coordinates a single poll-and-sync cycle."""

from __future__ import annotations

import hashlib
import time

import httpx
import structlog

from adapter import metrics
from adapter.fetcher import FileFetcher
from adapter.mapping_store import MappingStore
from adapter.models import SyncResult
from adapter.observer import FileObserver
from adapter.retriva_client import RetrivaClient

logger = structlog.get_logger(__name__)


class SyncOrchestrator:
    """Ties together observer, fetcher, Retriva client, and mapping store."""

    def __init__(
        self,
        observer: FileObserver,
        fetcher: FileFetcher,
        retriva: RetrivaClient,
        store: MappingStore,
    ) -> None:
        self._observer = observer
        self._fetcher = fetcher
        self._retriva = retriva
        self._store = store

    async def run_cycle(self) -> SyncResult:
        """Execute one full sync cycle.

        1. List files from OWUI
        2. Detect changes (new / removed)
        3. Ingest new files into Retriva
        4. Delete removed files from Retriva
        5. Retry previously failed ingestions
        6. Prune deleted mappings
        """
        start = time.monotonic()
        result = SyncResult()

        try:
            # --- 1. Observe ---
            owui_files = await self._observer.list_files()
            synced_ids = await self._store.get_synced_file_ids()
            changes = self._observer.detect_changes(owui_files, synced_ids)

            # --- 2. Ingest new files ---
            for file_info in changes.to_ingest:
                try:
                    fetched = await self._fetcher.download(file_info)
                    if fetched is None:
                        result.skipped += 1
                        continue

                    doc_id = await self._retriva.ingest(fetched)
                    content_hash = hashlib.sha256(fetched.content).hexdigest()

                    await self._store.create(
                        owui_file_id=file_info.id,
                        filename=file_info.filename,
                        retriva_doc_id=doc_id,
                        content_hash=content_hash,
                        status="synced",
                    )
                    result.ingested += 1
                    metrics.files_synced_total.inc()
                except (httpx.HTTPError, Exception) as exc:
                    logger.error(
                        "ingest_failed",
                        file_id=file_info.id,
                        filename=file_info.filename,
                        error=str(exc),
                    )
                    # Try to create a failed mapping so we retry later
                    try:
                        await self._store.create(
                            owui_file_id=file_info.id,
                            filename=file_info.filename,
                            retriva_doc_id="",
                            status="failed",
                        )
                    except Exception:
                        pass  # mapping may already exist
                    result.failed += 1
                    result.errors.append(f"ingest:{file_info.id}:{exc}")
                    metrics.sync_errors_total.inc()

            # --- 3. Delete removed files ---
            for owui_file_id in changes.to_delete:
                try:
                    mapping = await self._store.get_by_file_id(owui_file_id)
                    if mapping and mapping.retriva_doc_id:
                        await self._retriva.delete_document(
                            mapping.retriva_doc_id,
                        )
                    await self._store.update_status(owui_file_id, "deleted")
                    result.deleted += 1
                    metrics.files_deleted_total.inc()
                except (httpx.HTTPError, Exception) as exc:
                    logger.error(
                        "delete_failed",
                        owui_file_id=owui_file_id,
                        error=str(exc),
                    )
                    result.failed += 1
                    result.errors.append(f"delete:{owui_file_id}:{exc}")
                    metrics.sync_errors_total.inc()

            # --- 4. Retry failed ---
            failed_mappings = await self._store.list_all(status="failed")
            for mapping in failed_mappings:
                try:
                    # Re-download and re-ingest
                    from adapter.models import OWUIFile

                    file_info = OWUIFile(
                        id=mapping.owui_file_id,
                        filename=mapping.filename,
                    )
                    fetched = await self._fetcher.download(file_info)
                    if fetched is None:
                        # File no longer exists in OWUI — mark deleted
                        await self._store.update_status(
                            mapping.owui_file_id, "deleted",
                        )
                        continue

                    doc_id = await self._retriva.ingest(fetched)
                    content_hash = hashlib.sha256(fetched.content).hexdigest()

                    await self._store.update_status(
                        mapping.owui_file_id, "synced",
                    )
                    # Update the doc_id (need direct SQL since we only have
                    # update_status — we'll update both fields)
                    conn = self._store._conn  # noqa: SLF001
                    await conn.execute(
                        """
                        UPDATE file_mappings
                        SET retriva_doc_id = ?, content_hash = ?
                        WHERE owui_file_id = ?
                        """,
                        (doc_id, content_hash, mapping.owui_file_id),
                    )
                    await conn.commit()

                    result.retried += 1
                    metrics.files_synced_total.inc()
                    logger.info(
                        "retry_succeeded",
                        owui_file_id=mapping.owui_file_id,
                        doc_id=doc_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "retry_failed",
                        owui_file_id=mapping.owui_file_id,
                        error=str(exc),
                    )
                    # Leave as 'failed' for next cycle

            # --- 5. Prune ---
            await self._store.prune_deleted()

        except httpx.HTTPError as exc:
            logger.error("sync_cycle_failed", error=str(exc))
            result.errors.append(f"cycle:{exc}")
            metrics.sync_errors_total.inc()
        except Exception as exc:
            logger.exception("sync_cycle_unexpected_error", error=str(exc))
            result.errors.append(f"unexpected:{exc}")
            metrics.sync_errors_total.inc()

        elapsed = time.monotonic() - start
        metrics.poll_duration_seconds.observe(elapsed)

        logger.info(
            "sync_cycle_complete",
            ingested=result.ingested,
            deleted=result.deleted,
            failed=result.failed,
            retried=result.retried,
            skipped=result.skipped,
            duration_s=round(elapsed, 3),
        )
        return result
