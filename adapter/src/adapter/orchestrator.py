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

"""Sync orchestrator — coordinates a single poll-and-sync cycle."""

from __future__ import annotations

import hashlib
import time

import httpx


from adapter import metrics
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.mapping_store import MappingStore
from adapter.models import FetchedFile, SyncResult
from adapter.observer import FileObserver
from adapter.retriva_client import RetrivaClient

from adapter.logger import get_logger

logger = get_logger(__name__)


class SyncOrchestrator:
    """Ties together observer, fetcher, Retriva client, and mapping store."""

    def __init__(
        self,
        observer: FileObserver,
        fetcher: FileFetcher,
        retriva: RetrivaClient,
        store: MappingStore,
        ingestion_context: IngestionContext | None = None,
    ) -> None:
        self._observer = observer
        self._fetcher = fetcher
        self._retriva = retriva
        self._store = store
        self._ingestion_ctx = ingestion_context

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
                        content_type=file_info.content_type,
                        content_hash=content_hash,
                        status="synced",
                    )
                    result.ingested += 1
                    metrics.files_synced_total.inc()
                except (httpx.HTTPError, Exception) as exc:
                    logger.error(f"ingest_failed file_id={file_info.id} filename={file_info.filename} error={exc}")
                    # Try to create a failed mapping so we retry later
                    try:
                        await self._store.create(
                            owui_file_id=file_info.id,
                            filename=file_info.filename,
                            retriva_doc_id="",
                            content_type=file_info.content_type,
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
                    logger.error(f"delete_failed owui_file_id={owui_file_id} error={exc}")
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
                        content_type=mapping.content_type,
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
                    logger.info(f"retry_succeeded owui_file_id={mapping.owui_file_id} doc_id={doc_id}")
                except Exception as exc:
                    logger.warning(f"retry_failed owui_file_id={mapping.owui_file_id} error={exc}")
                    # Leave as 'failed' for next cycle

            # --- 5. Prune ---
            await self._store.prune_deleted()

        except httpx.HTTPError as exc:
            logger.error(f"sync_cycle_failed error={exc}")
            result.errors.append(f"cycle:{exc}")
            metrics.sync_errors_total.inc()
        except Exception as exc:
            logger.exception(f"sync_cycle_unexpected_error error={exc}")
            result.errors.append(f"unexpected:{exc}")
            metrics.sync_errors_total.inc()

        elapsed = time.monotonic() - start
        metrics.poll_duration_seconds.observe(elapsed)

        logger.info(f"sync_cycle_complete ingested={result.ingested} deleted={result.deleted} failed={result.failed} retried={result.retried} skipped={result.skipped} duration_s={round(elapsed, 3)}")
        return result

    # ------------------------------------------------------------------
    # Context-aware ingestion (webhook-triggered)
    # ------------------------------------------------------------------

    async def ingest_with_context(
        self,
        file_ids: list[str],
        chat_id: str,
    ) -> SyncResult:
        """Ingest specific files with metadata from the chat ingestion context.

        This is the webhook-triggered ingestion path.  Unlike ``run_cycle()``,
        it ingests *only* the specified files and enriches them with
        ``kb_ids`` and ``user_metadata`` from the active ingestion context.
        """
        result = SyncResult()

        # Resolve metadata payload from the ingestion context
        payload: dict = {}
        if self._ingestion_ctx:
            payload = self._ingestion_ctx.get_ingestion_payload(chat_id)

        kb_ids = tuple(payload.get("kb_ids", []))
        user_metadata = tuple(
            (k, v) for k, v in payload.get("user_metadata", {}).items()
        )

        for file_id in file_ids:
            try:
                # Check if already synced
                existing = await self._store.get_by_file_id(file_id)
                if existing and existing.status == "synced":
                    result.skipped += 1
                    continue

                # Build a minimal OWUIFile to drive the fetcher
                from adapter.models import OWUIFile

                file_info = OWUIFile(id=file_id, filename=f"webhook:{file_id}")

                fetched = await self._fetcher.download(file_info)
                if fetched is None:
                    result.skipped += 1
                    continue

                # Enrich with context metadata
                enriched = FetchedFile(
                    file_id=fetched.file_id,
                    filename=fetched.filename,
                    content_type=fetched.content_type,
                    content=fetched.content,
                    size=fetched.size,
                    kb_ids=kb_ids,
                    user_metadata=user_metadata,
                )

                doc_id = await self._retriva.ingest(enriched)
                content_hash = hashlib.sha256(enriched.content).hexdigest()

                if existing:
                    # Update failed → synced
                    await self._store.update_status(file_id, "synced")
                    conn = self._store._conn  # noqa: SLF001
                    await conn.execute(
                        """
                        UPDATE file_mappings
                        SET retriva_doc_id = ?, content_hash = ?
                        WHERE owui_file_id = ?
                        """,
                        (doc_id, content_hash, file_id),
                    )
                    await conn.commit()
                else:
                    await self._store.create(
                        owui_file_id=file_id,
                        filename=fetched.filename,
                        retriva_doc_id=doc_id,
                        content_type=fetched.content_type,
                        content_hash=content_hash,
                        status="synced",
                    )

                result.ingested += 1
                metrics.files_synced_total.inc()
                logger.info(
                    f"contextual_ingest_succeeded file_id={file_id} "
                    f"doc_id={doc_id} kb_ids={kb_ids} "
                    f"metadata_keys={[k for k, _ in user_metadata]}"
                )
            except Exception as exc:
                logger.error(f"contextual_ingest_failed file_id={file_id} error={exc}")
                try:
                    await self._store.create(
                        owui_file_id=file_id,
                        filename=f"webhook:{file_id}",
                        retriva_doc_id="",
                        content_type="application/octet-stream",
                        status="failed",
                    )
                except Exception:
                    pass
                result.failed += 1
                result.errors.append(f"ctx_ingest:{file_id}:{exc}")
                metrics.sync_errors_total.inc()

        return result