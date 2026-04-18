# Tasks — Thin Adapter (Pattern B-1)

**Status:** Final | **Version:** 1.0 | **Date:** 2026-04-18

---

## Phase 1 — Scaffolding & Config

- [ ] **T-01** Initialize Python project (`pyproject.toml`, `uv`, src layout)
- [ ] **T-02** Create `config.py` — Pydantic Settings with env var loading
- [ ] **T-03** Create `models.py` — shared dataclasses
- [ ] **T-04** Set up `structlog` JSON logging
- [ ] **T-05** Unit tests for config validation

## Phase 2 — Core Components

- [ ] **T-06** Implement `MappingStore` — SQLite CRUD
- [ ] **T-07** Unit tests for `MappingStore`
- [ ] **T-08** Implement `FileObserver` — poll OWUI, compute diff
- [ ] **T-09** Unit tests for `FileObserver`
- [ ] **T-10** Implement `FileFetcher` — download with retry
- [ ] **T-11** Unit tests for `FileFetcher`
- [ ] **T-12** Implement `RetrivaClient` — ingest & delete
- [ ] **T-13** Unit tests for `RetrivaClient`

## Phase 3 — Orchestration

- [ ] **T-14** Implement `SyncOrchestrator`
- [ ] **T-15** Implement failed-ingestion retry logic
- [ ] **T-16** Unit tests for orchestrator

## Phase 4 — HTTP Service

- [ ] **T-17** FastAPI app with `/healthz`, `/readyz`
- [ ] **T-18** `POST /api/v1/sync` endpoint
- [ ] **T-19** `GET /api/v1/mappings` endpoint
- [ ] **T-20** APScheduler periodic polling
- [ ] **T-21** `/metrics` Prometheus endpoint
- [ ] **T-22** Integration tests for HTTP endpoints

## Phase 5 — Containerization

- [ ] **T-23** `Dockerfile` (multi-stage, non-root, slim)
- [ ] **T-24** `docker-compose.yml` with volume mount
- [ ] **T-25** Smoke test: compose up → healthz → poll

## Phase 6 — E2E Testing

- [ ] **T-26** Upload file → adapter syncs → verify in Retriva
- [ ] **T-27** Delete file → adapter deletes → verify in Retriva
- [ ] **T-28** Restart adapter → verify no duplication
- [ ] **T-29** Retriva down → retry → succeeds when Retriva returns

## Phase 7 — Documentation

- [ ] **T-30** `README.md` with setup & usage
- [ ] **T-31** Update SDD document
