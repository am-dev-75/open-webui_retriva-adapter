# Acceptance Criteria — Thin Adapter (Pattern B-1)

**Status:** Final  
**Version:** 1.0  
**Date:** 2026-04-18  

---

## Functional Criteria

### AC-1: File Upload Mirroring

**Given** a user uploads a file in Open WebUI  
**When** the adapter completes its next poll cycle  
**Then** the file content is ingested into Retriva, and a mapping record
exists in the adapter's SQLite database linking `owui_file_id` to
`retriva_doc_id` with status `synced`.

### AC-2: Delete Propagation

**Given** a previously synced file is deleted from Open WebUI  
**When** the adapter completes its next poll cycle  
**Then** the corresponding Retriva document is deleted via
`DELETE /api/v1/documents/{doc_id}`, and the mapping record is marked
`deleted`.

### AC-3: Idempotent Sync

**Given** a file has already been synced (mapping exists with status `synced`)  
**When** the adapter runs another poll cycle  
**Then** the file is **not** re-downloaded or re-ingested. The mapping
count remains unchanged.

### AC-4: Restart Safety

**Given** the adapter process is killed and restarted  
**When** the next poll cycle runs  
**Then** no files are duplicated in Retriva. Previously synced files
retain their mappings. Only genuinely new files are ingested.

### AC-5: Failed Ingestion Retry

**Given** a file download or Retriva ingestion fails (transient error)  
**When** the mapping is marked `failed`  
**Then** the adapter retries the file on subsequent poll cycles until
it succeeds or reaches a configurable max retry count.

### AC-6: Force Sync

**Given** an operator sends `POST /api/v1/sync` to the adapter  
**Then** an immediate poll cycle is triggered regardless of the
scheduled interval, and the response includes the sync result summary.

---

## Non-Functional Criteria

### AC-7: Health Probes

- `GET /healthz` returns `200 {"status": "ok"}` when the adapter process
  is running.
- `GET /readyz` returns `200` only when both OWUI and Retriva are reachable;
  returns `503` otherwise.

### AC-8: Observability

- All sync operations emit structured JSON log entries with fields:
  `event`, `owui_file_id`, `filename`, `retriva_doc_id`, `status`,
  `duration_ms`.
- `GET /metrics` exposes Prometheus counters:
  - `adapter_files_synced_total`
  - `adapter_files_deleted_total`
  - `adapter_sync_errors_total`
  - `adapter_poll_duration_seconds` (histogram)

### AC-9: Configuration

- The adapter starts with only `OWUI_BASE_URL`, `OWUI_API_KEY`, and
  `RETRIVA_BASE_URL` set. All other config has working defaults.
- Invalid or missing required config causes a clear startup error with
  the name of the missing variable.

### AC-10: Open WebUI Independence

- Open WebUI functions normally (file upload, chat, knowledge bases)
  whether the adapter is running, stopped, or crashed.
- No Open WebUI source code, plugins, or pipelines are modified.

### AC-11: Container Readiness

- `docker compose up adapter` starts the adapter successfully.
- The adapter image builds in under 60 seconds on a warm cache.
- The container runs as a non-root user.

---

## Verification Matrix

| AC | Verification Method |
|---|---|
| AC-1 | Integration test: upload file → poll → assert mapping + Retriva doc exists |
| AC-2 | Integration test: delete file from OWUI → poll → assert Retriva doc gone |
| AC-3 | Unit test: run poll twice → assert single ingestion call |
| AC-4 | Integration test: kill adapter → restart → poll → assert no duplicates |
| AC-5 | Unit test: mock Retriva 500 → assert `failed` status → retry succeeds |
| AC-6 | Integration test: POST `/api/v1/sync` → assert immediate sync |
| AC-7 | Smoke test: curl `/healthz` and `/readyz` |
| AC-8 | Smoke test: grep structured logs; curl `/metrics` |
| AC-9 | Unit test: missing `OWUI_BASE_URL` → `ValidationError` with field name |
| AC-10 | Manual: stop adapter → verify OWUI still works |
| AC-11 | CI: `docker compose build adapter` + `docker compose up -d adapter` |
