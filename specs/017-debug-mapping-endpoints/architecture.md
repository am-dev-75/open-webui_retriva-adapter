# Architecture — Debug Mapping Endpoints

## Overview
The Thin Adapter persists state reflecting the relationship between Open WebUI identifiers and Retriva identifiers. This architecture adds observability to that state by introducing gated debug endpoints and expanding the `MappingStore`.

## Components Modified

### 1. `MappingStore`
The SQLite database backing the adapter will be expanded to include a new table `kb_mappings`.
Since Knowledge Base IDs are inherently a 1:1 pass-through to Retriva, the adapter's only responsibility is to track which Open WebUI Knowledge Bases have been observed during webhooks.
- **`file_mappings`**: Exists and persists `owui_file_id` ↔ `retriva_doc_id`.
- **`kb_mappings`** (NEW): Persists `owui_kb_id` mapped to `retriva_kb_id` (typically identical) along with the `last_seen_at` timestamp.

### 2. `main.py` Webhook Processing
The existing webhook receiver handles incoming KB IDs:
```python
if payload.kb_ids:
    _ingestion_ctx.set_kb_ids(payload.chat_id, payload.kb_ids)
```
This will be expanded to also upsert those KB IDs into the `kb_mappings` store asynchronously, updating their `last_seen_at` timestamp to provide an accurate debug view.

### 3. `_register_debug_endpoints`
The FastAPI application registers internal endpoints via `_register_debug_endpoints()`. This registration is strictly gated by the boolean flag `ENABLE_DEBUG_ENDPOINTS` (`THIN_ADAPTER_DEBUG_ENDPOINTS` in `.env`).

Endpoints:
- `GET /internal/mappings/documents`
- `GET /internal/mappings/documents/{owui_file_id}`
- `GET /internal/mappings/knowledge-bases`

## Data Flow
1. **Observation**: Open WebUI sends a chat webhook containing `kb_ids`.
2. **Persistence**: The adapter upserts these KB IDs into `kb_mappings` via the `MappingStore`.
3. **Retrieval**: The developer accesses `/internal/mappings/knowledge-bases`. The adapter queries the SQLite `MappingStore` and returns the rows.

## Failure Modes
- If `ENABLE_DEBUG_ENDPOINTS` is false, FastAPI returns a native `404 Not Found`.
- If the store fails to initialize or is queried before lifespan execution, the endpoints return a structured error or `503`.
- Persistence of KB IDs is a secondary operation and must not crash the primary webhook response if the SQLite write fails.
