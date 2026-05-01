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

"""FastAPI application — entry point for the adapter service."""

from __future__ import annotations

import asyncio
import dataclasses
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import generate_latest

from adapter import metrics
from adapter.config import VERSION, Settings, load_settings
from adapter.directive_parser import parse_directive
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.logger import setup_logging, get_logger
from adapter.mapping_store import MappingStore
from adapter.models import ChatMessagePayload, SyncResult
from adapter.observer import FileObserver
from adapter.chat_observer import ChatObserver
from adapter.orchestrator import SyncOrchestrator
from adapter.retriva_client import RetrivaClient
from adapter.synthetic_response import build_response
from adapter.turn_classifier import classify

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application state (populated during lifespan)
# ---------------------------------------------------------------------------
_settings: Settings | None = None
_store: MappingStore | None = None
_orchestrator: SyncOrchestrator | None = None
_scheduler: AsyncIOScheduler | None = None
_http_client: httpx.AsyncClient | None = None
_ingestion_ctx: IngestionContext | None = None
_chat_observer: ChatObserver | None = None
_sync_lock = asyncio.Lock()


async def _run_scheduled_sync() -> None:
    """Called by APScheduler on each file-sync interval tick."""
    async with _sync_lock:
        if _orchestrator:
            await _orchestrator.run_cycle()

async def _run_chat_poll() -> None:
    """Called by APScheduler on each chat-poll interval tick."""
    if _chat_observer and _ingestion_ctx:
        await _chat_observer.poll_for_directives(_ingestion_ctx)


def _apply_directive_if_needed(
    classification: Any,
    body: dict[str, Any],
) -> None:
    """Apply a parsed directive to the ingestion context (if applicable).

    Centralises the directive-application logic so it is called exactly
    once per turn, regardless of the routing decision.
    """
    if (
        classification.has_directive
        and classification.directive_result
        and _ingestion_ctx
    ):
        chat_id = body.get("chat_id", body.get("session_id", "default"))
        _ingestion_ctx.apply_directive(chat_id, classification.directive_result)


def _retriva_headers() -> dict[str, str]:
    """Build outbound headers for Retriva service-to-service calls.

    Uses ``RETRIVA_API_KEY`` — never the inbound Authorization header.
    The adapter terminates inbound user/UI auth at the boundary.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _settings and _settings.RETRIVA_API_KEY:
        headers["Authorization"] = f"Bearer {_settings.RETRIVA_API_KEY}"
    return headers


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201, ARG001
    """Manage adapter lifecycle: open store, start scheduler."""
    global _settings, _store, _orchestrator, _scheduler, _http_client, _ingestion_ctx  # noqa: PLW0603

    _settings = load_settings()
    setup_logging()
    logger.info(f"### Open Web UI Retriva adapter starting ... ({VERSION})")

    # HTTP client shared across components
    _http_client = httpx.AsyncClient(timeout=_settings.HTTP_TIMEOUT_SECONDS)

    # Ingestion context (ephemeral, in-memory)
    _ingestion_ctx = IngestionContext()

    # Components
    _store = MappingStore(_settings.DB_PATH)
    await _store.open()

    _ingestion_ctx = IngestionContext(
        default_kb_id=_settings.DEFAULT_KB_ID,
    )

    observer = FileObserver(_settings, _http_client)
    fetcher = FileFetcher(_settings, _http_client)
    retriva = RetrivaClient(_settings, _http_client)
    _orchestrator = SyncOrchestrator(
        observer, fetcher, retriva, _store,
        ingestion_context=_ingestion_ctx,
    )

    # Chat observer (directive detection via chat polling)
    if _settings.CHAT_POLL_ENABLED:
        _chat_observer = ChatObserver(_settings, _http_client)

    # Scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_scheduled_sync,
        "interval",
        seconds=_settings.POLL_INTERVAL_SECONDS,
        id="sync_cycle",
        max_instances=1,
    )
    if _settings.CHAT_POLL_ENABLED:
        _scheduler.add_job(
            _run_chat_poll,
            "interval",
            seconds=_settings.CHAT_POLL_INTERVAL_SECONDS,
            id="chat_poll",
            max_instances=1,
        )
    _scheduler.start()
    logger.info(f"scheduler_started fallback_sync_interval_s={_settings.POLL_INTERVAL_SECONDS}")
    if _settings.CHAT_POLL_ENABLED:
        logger.info(f"chat_poll_started fallback_interval_s={_settings.CHAT_POLL_INTERVAL_SECONDS}")

    # Register debug endpoints if enabled
    if _settings.ENABLE_DEBUG_ENDPOINTS:
        _register_debug_endpoints(app)
        logger.info("debug_endpoints_enabled")

    yield

    # Shutdown
    if _scheduler:
        _scheduler.shutdown(wait=False)
    if _http_client:
        await _http_client.aclose()
    if _store:
        await _store.close()
    logger.info("adapter_stopped")


app = FastAPI(
    title="Retriva Adapter",
    description="Thin adapter (Pattern B-1) — mirrors Open WebUI files into Retriva",
    version=VERSION,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health & readiness
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness probe — checks OWUI and Retriva connectivity."""
    checks: dict[str, bool] = {}

    # Check OWUI
    try:
        if _http_client and _settings:
            resp = await _http_client.get(
                f"{_settings.OWUI_BASE_URL.rstrip('/')}/api/v1/files/",
                headers={"Authorization": f"Bearer {_settings.OWUI_API_KEY}"},
            )
            checks["owui"] = resp.status_code == 200  # noqa: PLR2004
        else:
            checks["owui"] = False
    except Exception:
        checks["owui"] = False

    # Check Retriva
    try:
        retriva = RetrivaClient(_settings, _http_client)  # type: ignore[arg-type]
        checks["retriva"] = await retriva.health()
    except Exception:
        checks["retriva"] = False

    all_ok = all(checks.values())
    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible proxy endpoints (Retriva chat API)
# ---------------------------------------------------------------------------

@app.get("/v1/models")
async def list_models() -> JSONResponse:
    """Proxy the OpenAI-compatible model list from Retriva's chat API."""
    if not _settings or not _http_client:
        return JSONResponse(
            content={"object": "list", "data": []},
            status_code=503,
        )

    retriva_url = f"{_settings.retriva_chat_url}/v1/models"
    try:
        resp = await _http_client.get(
            retriva_url,
            headers=_retriva_headers(),
        )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPError as exc:
        logger.error(f"retriva_models_proxy_error error={exc}")
        return JSONResponse(
            content={"object": "list", "data": []},
            status_code=502,
        )

@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """OpenAI-compatible chat completions endpoint with UX-aware routing.

    Classifies each turn and either:
    - Returns a synthetic acknowledgement for directive/upload turns
    - Forwards the request to Retriva for substantive questions

    The adapter never calls the LLM directly.  Retriva owns the LLM
    credentials and handles RAG retrieval + completion.
    """
    body: dict[str, Any] = await request.json()

    logger.debug(f"### Chat request received. body={body}")

    # Classify the turn
    chat_id = body.get("chat_id", body.get("session_id", "default"))
    is_ingestion_active = False
    if _ingestion_ctx:
        is_ingestion_active = _ingestion_ctx.is_active(chat_id)

    classification = classify(body, is_ingestion_active=is_ingestion_active)
    route = classification.route

    # Apply directive to ingestion context once, before branching
    _apply_directive_if_needed(classification, body)

    # --- Proactive Ingestion (for all turns) ---
    # Trigger proactive sync if files are detected in the request, regardless of routing.
    # This provides a robust fallback if the Filter or Webhooks fail to notify the adapter.
    if _orchestrator:
        # Extract file IDs from markers (resource-id="...") in the request body
        file_ids = re.findall(r'resource-id="([a-f0-9-]{36})"', str(body))
        if file_ids:
            logger.info(f"proactive_ingestion_triggered chat_id={chat_id} file_ids={file_ids} route={route}")
            # Fire and forget ingestion in the background so we don't block the UI
            asyncio.create_task(_orchestrator.ingest_with_context(file_ids, chat_id))

    # --- Intercepted routes: return synthetic acknowledgement ---
    if route != "forward":
        synthetic = build_response(classification)
        metrics.turns_intercepted_total.labels(route=route).inc()
        return JSONResponse(content=synthetic)

    # --- Forward route: proxy to Retriva ---
    # Strip directives from the user message before forwarding
    if classification.has_directive and classification.stripped_content:
        messages = body.get("messages", [])
        for msg in reversed(messages):
            if msg.get("role") == "user":
                msg["content"] = classification.stripped_content
                break

    retriva_url = (
        f"{_settings.retriva_chat_url}/v1/chat/completions"  # type: ignore[union-attr]
    )
    is_streaming = body.get("stream", False)

    try:
        if is_streaming:
            upstream_resp = await _http_client.send(  # type: ignore[union-attr]
                _http_client.build_request(  # type: ignore[union-attr]
                    "POST",
                    retriva_url,
                    json=body,
                    headers=_retriva_headers(),
                ),
                stream=True,
            )

            async def _stream_generator():
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_resp.aclose()

            metrics.turns_forwarded_total.inc()
            return StreamingResponse(
                _stream_generator(),
                status_code=upstream_resp.status_code,
                media_type=upstream_resp.headers.get(
                    "content-type", "text/event-stream",
                ),
            )
        else:
            resp = await _http_client.post(  # type: ignore[union-attr]
                retriva_url,
                json=body,
                headers=_retriva_headers(),
            )
            metrics.turns_forwarded_total.inc()
            return JSONResponse(
                content=resp.json(), status_code=resp.status_code,
            )

    except httpx.HTTPError as exc:
        logger.error(f"retriva_proxy_error error={exc}")
        return JSONResponse(
            content={
                "error": {
                    "message": f"Retriva proxy error: {exc}",
                    "type": "proxy_error",
                },
            },
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Sync & mappings API
# ---------------------------------------------------------------------------

@app.post("/api/v1/sync")
async def force_sync() -> dict[str, Any]:
    """Trigger an immediate sync cycle."""
    if not _orchestrator:
        return {"error": "adapter not initialized"}

    async with _sync_lock:
        result: SyncResult = await _orchestrator.run_cycle()

    return {
        "ingested": result.ingested,
        "deleted": result.deleted,
        "failed": result.failed,
        "retried": result.retried,
        "skipped": result.skipped,
        "errors": result.errors,
    }


@app.get("/api/v1/mappings")
async def list_mappings() -> list[dict[str, Any]]:
    """Return all current file ↔ document mappings."""
    if not _store:
        return []

    records = await _store.list_all()
    return [
        {
            "owui_file_id": r.owui_file_id,
            "filename": r.filename,
            "retriva_doc_id": r.retriva_doc_id,
            "content_hash": r.content_hash,
            "status": r.status,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# Chat message webhook (directive parsing + contextual ingestion)
# ---------------------------------------------------------------------------

@app.post("/api/v1/chat/message")
async def receive_chat_message(payload: ChatMessagePayload) -> dict[str, Any]:
    """Receive a chat message from Open WebUI (via Action/Function).

    Parses ingestion directives and updates per-chat ingestion context.
    If ``file_ids`` are present and the context is active, triggers
    contextual ingestion with metadata.
    """
    if not _ingestion_ctx or not _orchestrator:
        return {"error": "adapter not initialized"}

    metrics.webhook_messages_total.inc()
    logger.debug(f"DEBUG: receive_chat_message chat_id={payload.chat_id!r} message={payload.message!r} file_ids={payload.file_ids!r}")

    # 1. Update KB IDs (always, independent of directives)
    if payload.kb_ids:
        _ingestion_ctx.set_kb_ids(payload.chat_id, payload.kb_ids)
        if _store:
            for kb_id in payload.kb_ids:
                try:
                    await _store.upsert_kb_mapping(kb_id)
                except Exception as e:
                    logger.error(f"failed to upsert kb_mapping kb_id={kb_id} err={e}")

    # 2. Parse directive from message
    directive = parse_directive(payload.message)

    # 3. Apply directive to ingestion context
    _ingestion_ctx.apply_directive(payload.chat_id, directive)

    if directive.action != "none":
        metrics.directives_processed_total.labels(action=directive.action).inc()

    # 4. If files attached and context is active, ingest with metadata
    result_data: dict[str, Any] = {
        "chat_id": payload.chat_id,
        "directive": directive.action,
        "tagging_active": _ingestion_ctx.is_active(payload.chat_id),
    }

    if payload.file_ids:
        async with _sync_lock:
            ingest_result = await _orchestrator.ingest_with_context(
                payload.file_ids, payload.chat_id,
            )
        result_data["ingestion"] = {
            "ingested": ingest_result.ingested,
            "skipped": ingest_result.skipped,
            "failed": ingest_result.failed,
            "errors": ingest_result.errors,
        }

    return result_data


# ---------------------------------------------------------------------------
# System events webhook (Knowledge base changes)
# ---------------------------------------------------------------------------

@app.post("/api/v1/events")
async def receive_owui_event(request: Request) -> dict[str, Any]:
    """Receive system-level events from Open WebUI Webhooks.

    Handles 'knowledge' and 'file' events for immediate sync, replacing
    the need for frequent polling.
    """
    if not _orchestrator:
        return {"error": "adapter not initialized"}

    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event", "unknown")
    # Open WebUI often puts the payload in a key named after the entity (e.g., 'file', 'knowledge', 'user')
    # or in a generic 'data' key. We check them all.
    payload = event_data.get("data") or event_data.get("knowledge") or event_data.get("file") or event_data.get("user") or event_data.get("chat") or {}

    logger.info(f"owui_event_received type={event_type} payload_keys={list(payload.keys())}")

    # knowledge.document.added | file.created | new_user (can trigger a sync for the new user)
    if event_type in ("knowledge.document.added", "file.created"):
        file_id = payload.get("id")
        if file_id:
            async with _sync_lock:
                # Global knowledge uploads use 'default' context
                await _orchestrator.ingest_with_context([file_id], "default")
            return {"status": "ingestion_triggered", "file_id": file_id}

    # knowledge.document.deleted | file.deleted
    elif event_type in ("knowledge.document.deleted", "file.deleted"):
        file_id = payload.get("id")
        if file_id:
            success = await _orchestrator.delete_by_file_id(file_id)
            return {
                "status": "deletion_processed",
                "file_id": file_id,
                "success": success,
            }

    return {"status": "ignored", "event_type": event_type}


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """Prometheus scrape endpoint."""
    return generate_latest().decode("utf-8")


# ---------------------------------------------------------------------------
# Debug endpoints (gated by THIN_ADAPTER_DEBUG_ENDPOINTS)
# ---------------------------------------------------------------------------

def _register_debug_endpoints(target_app: FastAPI) -> None:
    """Register internal debug endpoints on the given app.

    Called only when ``THIN_ADAPTER_DEBUG_ENDPOINTS=true``.
    These endpoints are NOT part of the public API surface.
    """

    @target_app.get("/internal/ingestion-tagging/{chat_id}")
    async def get_ingestion_tagging(chat_id: str) -> dict[str, Any]:
        """Return the current ingestion context state for a chat."""
        if not _ingestion_ctx:
            return {"error": "ingestion context not initialized"}

        info = _ingestion_ctx.get_debug_info(chat_id)
        if info is None:
            return {
                "chat_id": chat_id,
                "state": "INACTIVE",
                "user_metadata": {},
                "kb_ids": [],
                "last_updated": None,
            }
        return info

    @target_app.get("/internal/mappings/documents")
    async def list_document_mappings() -> list[dict[str, Any]]:
        """List all document mappings."""
        if not _store:
            return []
        
        records = await _store.list_all()
        return [dataclasses.asdict(r) for r in records]

    @target_app.get("/internal/mappings/documents/{owui_file_id}")
    async def get_document_mapping(owui_file_id: str) -> dict[str, Any]:
        """Get a specific document mapping by OWUI file ID."""
        if not _store:
            raise HTTPException(status_code=404, detail="Store not initialized")
            
        record = await _store.get_by_file_id(owui_file_id)
        if not record:
            raise HTTPException(status_code=404, detail="Mapping not found")
            
        return dataclasses.asdict(record)

    @target_app.get("/internal/mappings/knowledge-bases")
    async def get_kb_mappings() -> list[dict[str, Any]]:
        """Return all observed Knowledge Base mappings."""
        if not _store:
            return []
            
        records = await _store.list_kb_mappings()
        return [
            {
                "owui_kb_id": r.owui_kb_id,
                "retriva_kb_id": r.retriva_kb_id,
                "last_seen_at": r.last_seen_at
            }
            for r in records
        ]