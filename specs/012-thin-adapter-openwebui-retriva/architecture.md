# Architecture — Thin Adapter (Pattern B-1)

**Status:** Final  
**Version:** 1.0  
**Date:** 2026-04-18  

---

## 1. System Context

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│              │       │              │       │              │
│  Open WebUI  │◄─poll─┤   Adapter    ├─ingest┤   Retriva    │
│  (OWUI)      │       │  (B-1)       │       │  (RAG)       │
│              │       │              │       │              │
└──────────────┘       └──────┬───────┘       └──────────────┘
                              │
                       ┌──────┴───────┐
                       │   SQLite     │
                       │   Mappings   │
                       └──────────────┘
```

The adapter sits between Open WebUI and Retriva as a **sidecar process**.
It has no inbound dependency from either system — both OWUI and Retriva
function normally if the adapter is stopped.

---

## 2. Components

### 2.1 FileObserver (Polling)

**Responsibility:** Periodically query OWUI to discover new and removed files.

| Detail | Value |
|---|---|
| Strategy | Polling via `GET /api/v1/files` |
| Interval | Configurable (`POLL_INTERVAL_SECONDS`, default 30s) |
| Diff logic | Compare OWUI file list against local mapping DB |
| Output | Two sets: `files_to_ingest` and `files_to_delete` |

**Diff algorithm:**

```
owui_ids   = { f.id for f in owui_files }
mapped_ids = { m.owui_file_id for m in mappings }

to_ingest = owui_ids - mapped_ids     # new files
to_delete = mapped_ids - owui_ids     # removed files
```

**Idempotency:** A file is only ingested if no mapping exists for its
`file_id`. Hash-based dedup is a future enhancement.

### 2.2 FileFetcher

**Responsibility:** Download raw file content from OWUI.

| Detail | Value |
|---|---|
| Endpoint | `GET /api/v1/files/{id}/content` |
| Auth | `Authorization: Bearer <OWUI_API_KEY>` |
| Timeout | 60s (configurable) |
| Error handling | Transient HTTP errors → retry with backoff; 404 → skip and log |

Returns a `FetchedFile` dataclass:

```python
@dataclass
class FetchedFile:
    file_id: str
    filename: str
    content_type: str
    content: bytes
    size: int
```

### 2.3 RetrivaClient

**Responsibility:** Forward files to Retriva ingestion and propagate deletions.

| Operation | Method | Endpoint | Payload |
|---|---|---|---|
| Ingest | `POST` | `/api/v1/ingest` | `multipart/form-data`: `file` + `metadata` JSON |
| Delete | `DELETE` | `/api/v1/documents/{doc_id}` | — |
| Health | `GET` | `/healthz` | — |

**Ingest metadata payload:**

```json
{
  "source": "openwebui",
  "source_file_id": "<owui_file_id>",
  "filename": "<original_filename>"
}
```

**Return:** Retriva responds with a `doc_id` (or list of doc IDs) that the
adapter stores in the mapping DB.

**Error handling:**
- 5xx / timeout → retry with exponential backoff (max 3 attempts)
- 4xx → log error, mark file as `failed` in mapping DB, skip

### 2.4 MappingStore (SQLite)

**Responsibility:** Durable storage for file ↔ document relationships.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS file_mappings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owui_file_id  TEXT    NOT NULL UNIQUE,
    filename      TEXT    NOT NULL,
    content_hash  TEXT,                        -- SHA-256 of file content
    retriva_doc_id TEXT   NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'synced',  -- synced | failed | deleted
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_owui_file_id ON file_mappings(owui_file_id);
CREATE INDEX IF NOT EXISTS idx_status ON file_mappings(status);
```

**Status lifecycle:**

```
(new file detected) ──► ingesting ──► synced
                                  └──► failed  (retry next cycle)

(file removed from OWUI) ──► deleting ──► deleted ──► (row pruned)
```

### 2.5 AdapterService (HTTP)

**Responsibility:** Expose health, metrics, and admin endpoints.

| Endpoint | Method | Description |
|---|---|---|
| `/healthz` | `GET` | Liveness probe — returns `{"status": "ok"}` |
| `/readyz` | `GET` | Readiness probe — checks OWUI + Retriva connectivity |
| `/metrics` | `GET` | Prometheus metrics (counters, gauges, histograms) |
| `/api/v1/sync` | `POST` | Force an immediate poll-and-sync cycle |
| `/api/v1/mappings` | `GET` | Return all current mappings as JSON |

**Framework:** FastAPI (lightweight, async-native, OpenAPI docs built-in).

### 2.6 SyncOrchestrator

**Responsibility:** Coordinate a single sync cycle end-to-end.

```
poll() pipeline:

  1. FileObserver.detect_changes()
       → (to_ingest: List[FileInfo], to_delete: List[Mapping])

  2. For each file in to_ingest:
       a. FileFetcher.download(file_id)
       b. RetrivaClient.ingest(fetched_file)
       c. MappingStore.create(owui_file_id, retriva_doc_id)

  3. For each mapping in to_delete:
       a. RetrivaClient.delete(retriva_doc_id)
       b. MappingStore.mark_deleted(owui_file_id)

  4. MappingStore.retry_failed()
       → re-attempt previously failed ingestions
```

---

## 3. Data Flow

```
 User uploads file.pdf in Open WebUI
              │
              ▼
 ┌─ OWUI stores file internally ──────────────────────┐
 │  file_id = "abc-123"                                │
 │  GET /api/v1/files → includes "abc-123"             │
 └─────────────────────────────────────────────────────┘
              │
     (adapter poll cycle)
              │
              ▼
 ┌─ Adapter detects new file ─────────────────────────┐
 │  "abc-123" not in mapping DB → download it          │
 │  GET /api/v1/files/abc-123/content → bytes          │
 └─────────────────────────────────────────────────────┘
              │
              ▼
 ┌─ Adapter forwards to Retriva ──────────────────────┐
 │  POST /api/v1/ingest (file bytes + metadata)        │
 │  Retriva returns doc_id = "ret-789"                 │
 └─────────────────────────────────────────────────────┘
              │
              ▼
 ┌─ Adapter persists mapping ─────────────────────────┐
 │  INSERT (owui_file_id="abc-123",                    │
 │          retriva_doc_id="ret-789",                  │
 │          status="synced")                           │
 └─────────────────────────────────────────────────────┘
```

---

## 4. Failure Handling

| Failure | Behavior |
|---|---|
| OWUI unreachable | Log warning, skip cycle, retry next interval |
| File download 404 | Log info (file may have been deleted mid-cycle), skip |
| File download timeout | Retry with backoff (max 3), then mark `failed` |
| Retriva unreachable | Log warning, skip ingestion, retry next cycle |
| Retriva ingest 4xx | Log error, mark mapping `failed`, skip |
| Retriva ingest 5xx | Retry with backoff (max 3), then mark `failed` |
| Retriva delete fails | Log error, keep mapping as `synced`, retry next cycle |
| SQLite write error | Fatal — adapter crashes, relies on container restart |
| Duplicate ingestion | Prevented by `UNIQUE(owui_file_id)` constraint |

**Backoff strategy:** Exponential with jitter — `delay = min(base * 2^n + jitter, max_delay)`  
**Defaults:** `base=1s`, `max_delay=30s`, `max_retries=3`

---

## 5. Deployment Topology

```yaml
# docker-compose.yml (relevant services)
services:
  openwebui:
    image: ghcr.io/open-webui/open-webui:latest
    ports: ["3000:8080"]

  retriva:
    image: retriva:latest
    ports: ["8400:8400"]

  adapter:
    build: ./adapter
    depends_on: [openwebui, retriva]
    environment:
      OWUI_BASE_URL: http://openwebui:8080
      OWUI_API_KEY: ${OWUI_API_KEY}
      RETRIVA_BASE_URL: http://retriva:8400
      POLL_INTERVAL_SECONDS: "30"
      DB_PATH: /data/adapter.db
    volumes:
      - adapter-data:/data
    ports: ["8500:8500"]
    restart: unless-stopped

volumes:
  adapter-data:
```

---

## 6. Project Structure

```
adapter/
├── pyproject.toml
├── Dockerfile
├── src/
│   └── adapter/
│       ├── __init__.py
│       ├── main.py              # Entry point: FastAPI app + scheduler
│       ├── config.py            # Pydantic Settings from env vars
│       ├── observer.py          # FileObserver — poll OWUI
│       ├── fetcher.py           # FileFetcher — download files
│       ├── retriva_client.py    # RetrivaClient — ingest & delete
│       ├── mapping_store.py     # MappingStore — SQLite CRUD
│       ├── orchestrator.py      # SyncOrchestrator — ties it together
│       ├── models.py            # Pydantic / dataclass models
│       └── metrics.py           # Prometheus counters & gauges
└── tests/
    ├── conftest.py
    ├── test_observer.py
    ├── test_fetcher.py
    ├── test_retriva_client.py
    ├── test_mapping_store.py
    └── test_orchestrator.py
```

---

## 7. Technology Choices

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Matches Retriva stack; team familiarity |
| HTTP framework | FastAPI | Async, lightweight, built-in OpenAPI |
| HTTP client | httpx | Async, timeout control, retry support |
| Database | SQLite (aiosqlite) | Zero-dependency, file-based, sufficient for mapping volume |
| Scheduling | APScheduler | In-process interval jobs, async support |
| Metrics | prometheus-client | Standard Python Prometheus library |
| Logging | structlog | JSON structured logging |
| Packaging | pyproject.toml + uv | Modern Python packaging |
| Container | Debian slim base | Small image, compatible with OWUI/Retriva stack |

---

## 8. Security Considerations

| Concern | Mitigation |
|---|---|
| API key exposure | Keys injected via env vars / secrets; never logged |
| Network trust | Adapter communicates over internal Docker network only |
| SQLite access | File permissions restricted to adapter process user |
| Input validation | File metadata validated before ingestion forwarding |
| Dependency supply chain | Pinned dependencies; `uv.lock` committed |
