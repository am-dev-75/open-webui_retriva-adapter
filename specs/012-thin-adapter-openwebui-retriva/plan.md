# Implementation Plan — Thin Adapter (Pattern B-1)

**Status:** Final | **Version:** 1.0 | **Date:** 2026-04-18

---

## Overview

Build a Python sidecar service that polls Open WebUI for file changes and
mirrors them into Retriva. 7 phases, 31 tasks, estimated 3–4 working days.

---

## Phase 1 — Scaffolding & Config (T-01 → T-05)

**Goal:** Runnable project skeleton with validated configuration.

1. `uv init` with src layout, Python 3.12+
2. Dependencies: `fastapi`, `uvicorn`, `httpx`, `pydantic-settings`,
   `aiosqlite`, `apscheduler`, `structlog`, `prometheus-client`
3. `config.py`: Pydantic `BaseSettings` loading from env vars
4. `models.py`: `FetchedFile`, `MappingRecord`, `SyncResult` dataclasses
5. Structured JSON logging via `structlog`

**Exit criterion:** `python -m adapter` starts, logs config, exits cleanly.

---

## Phase 2 — Core Components (T-06 → T-13)

**Goal:** Four independently testable modules.

| Module | Input | Output |
|---|---|---|
| `MappingStore` | SQL operations | CRUD on `file_mappings` table |
| `FileObserver` | OWUI file list + mappings | `to_ingest` / `to_delete` sets |
| `FileFetcher` | `file_id` | `FetchedFile` (bytes + metadata) |
| `RetrivaClient` | `FetchedFile` or `doc_id` | `doc_id` (ingest) or ack (delete) |

Each module gets a unit test file with mocked HTTP using `respx`.

**Exit criterion:** All 4 modules pass unit tests in isolation.

---

## Phase 3 — Orchestration (T-14 → T-16)

**Goal:** End-to-end sync cycle in a single function call.

`SyncOrchestrator.run_cycle()` wires the four components:
1. Observe → 2. Fetch → 3. Ingest → 4. Map → 5. Delete → 6. Retry failed

**Exit criterion:** Orchestrator unit test passes with mocked dependencies.

---

## Phase 4 — HTTP Service (T-17 → T-22)

**Goal:** FastAPI app with health, admin, and metrics endpoints.

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Liveness |
| `GET /readyz` | OWUI + Retriva connectivity |
| `POST /api/v1/sync` | Force immediate sync |
| `GET /api/v1/mappings` | Inspect current state |
| `GET /metrics` | Prometheus scrape target |

APScheduler runs `SyncOrchestrator.run_cycle()` every `POLL_INTERVAL_SECONDS`.

**Exit criterion:** `uvicorn adapter.main:app` starts, serves all endpoints.

---

## Phase 5 — Containerization (T-23 → T-25)

**Goal:** Production-ready Docker image.

- Multi-stage build (builder + runtime)
- Non-root `adapter` user
- Volume mount for SQLite at `/data`
- Health check: `CMD curl -f http://localhost:8500/healthz`

**Exit criterion:** `docker compose up adapter` → `/healthz` returns 200.

---

## Phase 6 — Integration Testing (T-26 → T-29)

**Goal:** Validate against real (or mock) OWUI and Retriva instances.

Test scenarios:
1. Upload → sync → verify Retriva document exists
2. Delete → sync → verify Retriva document removed
3. Kill adapter → restart → verify no duplication
4. Retriva down → retry → verify eventual success

**Exit criterion:** All 4 E2E scenarios pass.

---

## Phase 7 — Documentation (T-30 → T-31)

**Goal:** Operator-ready docs.

- `README.md`: quickstart, config reference, troubleshooting
- SDD update: final architecture record

**Exit criterion:** A new operator can deploy the adapter from README alone.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OWUI file list API changes in future versions | Medium | High | Pin tested OWUI version; adapter logs schema warnings |
| Large files exhaust adapter memory | Low | Medium | Stream file downloads; set max file size config |
| SQLite contention under high load | Low | Low | Single-writer architecture; WAL mode enabled |
| Retriva ingestion endpoint differs from spec | Medium | Medium | Confirm endpoints against live Retriva before Phase 2 |
