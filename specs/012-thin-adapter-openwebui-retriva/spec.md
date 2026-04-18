# Feature Spec — Thin Adapter (Pattern B-1)

**Status:** Final  
**Version:** 1.0  
**Date:** 2026-04-18  

---

## 1. Goal

Enable Open WebUI native file uploads to be **automatically mirrored** into
Retriva ingestion pipelines, without modifying Open WebUI source code.

Users upload files through Open WebUI's standard "+" button. The adapter
detects those files, downloads them, forwards them to Retriva for ingestion,
and stores the resulting mapping. Deleting a file in Open WebUI triggers the
adapter to remove the corresponding Retriva documents.

The adapter is **invisible** to end-users; it is an operator-deployed sidecar.

---

## 2. Terminology

| Term | Definition |
|---|---|
| **Open WebUI (OWUI)** | The chat frontend; source of file uploads |
| **Retriva** | The RAG backend; owns ingestion, chunking, embedding, and retrieval |
| **Adapter** | This component (Pattern B-1); the thin bridge between OWUI and Retriva |
| **Mapping** | A durable record linking an OWUI `file_id` to a Retriva `doc_id` |
| **Knowledge Base (KB)** | An OWUI organizational unit grouping files; maps 1:1 to a Retriva collection |

---

## 3. In Scope

| # | Capability | Description |
|---|---|---|
| S-1 | File detection | Poll OWUI `/api/v1/files` to discover newly uploaded files |
| S-2 | File download | Fetch raw file content via `GET /api/v1/files/{id}/content` |
| S-3 | Retriva ingestion | Forward file bytes to Retriva ingestion endpoint |
| S-4 | Mapping persistence | Store `file_id ↔ doc_id` in a durable SQLite database |
| S-5 | Delete propagation | Detect file removal in OWUI and delete matching Retriva documents |
| S-6 | Health endpoint | `GET /healthz` for liveness probes |
| S-7 | Configuration | Env-var driven config (OWUI URL, Retriva URL, API keys, poll interval) |
| S-8 | Observability | Structured JSON logging, Prometheus-compatible `/metrics` |

---

## 4. Out of Scope

| # | Exclusion | Rationale |
|---|---|---|
| O-1 | Retrieval / search logic | Retriva owns this entirely |
| O-2 | Embedding logic | Retriva owns this entirely |
| O-3 | UI changes | Open WebUI is unmodified |
| O-4 | Multi-tenant user separation | v1 assumes a single operator API key |
| O-5 | Webhook-based observation | Future enhancement (roadmap v0.7+) |
| O-6 | Knowledge base auto-creation | OWUI KBs are created manually; adapter only syncs files |

---

## 5. External API Contracts

### 5.1 Open WebUI (consumed by adapter)

| Operation | Method | Endpoint | Notes |
|---|---|---|---|
| List files | `GET` | `/api/v1/files` | Returns `[FileObject]`; paginated |
| Download file | `GET` | `/api/v1/files/{id}/content` | Raw bytes |
| ~~Delete file~~ | — | — | Adapter detects absence, not deletion events |

**Auth:** `Authorization: Bearer <OWUI_API_KEY>`

**FileObject schema (relevant fields):**

```json
{
  "id": "uuid",
  "filename": "report.pdf",
  "hash": "sha256-hex",
  "meta": {
    "name": "report.pdf",
    "content_type": "application/pdf",
    "size": 1048576
  },
  "created_at": 1715000000000,
  "updated_at": 1715000000000
}
```

### 5.2 Retriva (consumed by adapter)

| Operation | Method | Endpoint | Notes |
|---|---|---|---|
| Ingest file | `POST` | `/api/v1/ingest` | `multipart/form-data` with file + metadata |
| Delete document | `DELETE` | `/api/v1/documents/{doc_id}` | Removes chunks + vectors |
| Health check | `GET` | `/healthz` | Validates Retriva availability |

> [!IMPORTANT]
> The exact Retriva endpoints will be confirmed against the live Retriva
> codebase during implementation. The above are based on the existing
> ingestion API from previous work.

### 5.3 Adapter (exposed)

| Operation | Method | Endpoint | Notes |
|---|---|---|---|
| Health | `GET` | `/healthz` | Returns `{"status": "ok"}` |
| Metrics | `GET` | `/metrics` | Prometheus text format |
| Force sync | `POST` | `/api/v1/sync` | Trigger immediate poll cycle |
| List mappings | `GET` | `/api/v1/mappings` | Returns current file↔doc mappings |

---

## 6. Configuration

All configuration is via environment variables with sensible defaults:

| Variable | Required | Default | Description |
|---|---|---|---|
| `OWUI_BASE_URL` | ✅ | — | Open WebUI base URL (e.g. `http://openwebui:3000`) |
| `OWUI_API_KEY` | ✅ | — | Bearer token for OWUI API |
| `RETRIVA_BASE_URL` | ✅ | — | Retriva base URL (e.g. `http://retriva:8400`) |
| `RETRIVA_API_KEY` | ❌ | — | Optional Retriva auth token |
| `POLL_INTERVAL_SECONDS` | ❌ | `30` | Seconds between polling cycles |
| `DB_PATH` | ❌ | `./data/adapter.db` | SQLite database path for mappings |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging level |
| `ADAPTER_PORT` | ❌ | `8500` | HTTP port for health/metrics/API |

---

## 7. Operational Constraints

| Constraint | Detail |
|---|---|
| **Stateless compute** | Adapter process can be killed and restarted at any time |
| **Durable state** | Only the SQLite mapping DB needs persistence (volume mount) |
| **Idempotent sync** | Re-running a poll cycle must not duplicate ingestions |
| **Graceful degradation** | If Retriva is down, adapter logs errors and retries next cycle |
| **No OWUI modification** | Adapter uses only public OWUI API; no forks, no plugins |
| **Containerized** | Must run as a standalone Docker container or Compose service |

---

## 8. Acceptance Summary

Users upload files in Open WebUI. Those files are automatically ingested
into Retriva and are available for RAG queries. Deleting a file in Open WebUI
causes the adapter to remove the corresponding Retriva documents. The
adapter can be restarted at any time without data loss or duplication.
