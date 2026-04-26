# Feature Spec — Debug Mapping Endpoints

## Goal
Provide read-only internal endpoints to inspect Open WebUI ↔ Retriva identifier mappings for troubleshooting and verification, strictly gated by configuration.

## In scope
- `GET /internal/mappings/documents` (list all document mappings)
- `GET /internal/mappings/documents/{owui_file_id}` (single document mapping lookup)
- `GET /internal/mappings/knowledge-bases` (list all knowledge base mappings)
- Expanding `MappingStore` to persist Knowledge Base ID observations.
- Disabling these endpoints in production unless `ENABLE_DEBUG_ENDPOINTS=true`.

## Out of scope
- Mutating endpoints (e.g., POST, PUT, DELETE for mappings).
- Exposing endpoints outside of the `/internal/` path prefix.
- Generating mappings out of thin air (mappings must reflect observed state).

## Functional requirements

### FR1 — Read-only observation
Endpoints MUST strictly perform `SELECT` queries on the underlying mapping stores. No state changes shall occur as a result of calling these endpoints.

### FR2 — Document Mapping Store
The document mapping endpoints MUST query the existing `file_mappings` table within the SQLite store.

### FR3 — Knowledge Base Mapping Store
The adapter MUST persist observed Open WebUI Knowledge Base IDs into a new `kb_mappings` table within the SQLite store. The `GET /internal/mappings/knowledge-bases` endpoint MUST query this table to return the list of KBs observed by the adapter.

### FR4 — Configuration Gating
The internal endpoints MUST return a `404 Not Found` if `ENABLE_DEBUG_ENDPOINTS` is missing or set to `false`.

### FR5 — Non-blocking operation
The persistence of KB mappings must happen synchronously or asynchronously in a manner that does not block the critical path of the webhook processing or document ingestion.
