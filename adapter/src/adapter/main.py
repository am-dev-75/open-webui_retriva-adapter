# SPDX-License-Identifier: MIT
"""FastAPI application — entry point for the adapter service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import generate_latest

from adapter import metrics
from adapter.config import VERSION, Settings, load_settings
from adapter.fetcher import FileFetcher
from adapter.ingestion_context import IngestionContext
from adapter.logger import setup_logging, get_logger
from adapter.mapping_store import MappingStore
from adapter.models import SyncResult
from adapter.observer import FileObserver
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
_sync_lock = asyncio.Lock()


async def _run_scheduled_sync() -> None:
    """Called by APScheduler on each interval tick."""
    async with _sync_lock:
        if _orchestrator:
            await _orchestrator.run_cycle()


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

    observer = FileObserver(_settings, _http_client)
    fetcher = FileFetcher(_settings, _http_client)
    retriva = RetrivaClient(_settings, _http_client)
    _orchestrator = SyncOrchestrator(observer, fetcher, retriva, _store)

    # Scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_scheduled_sync,
        "interval",
        seconds=_settings.POLL_INTERVAL_SECONDS,
        id="sync_cycle",
        max_instances=1,
    )
    _scheduler.start()
    logger.info(f"scheduler_started interval_s={_settings.POLL_INTERVAL_SECONDS}")

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
# Prometheus metrics
# ---------------------------------------------------------------------------

@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """Prometheus scrape endpoint."""
    return generate_latest().decode("utf-8")
