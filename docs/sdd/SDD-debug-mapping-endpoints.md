# SDD Pack — Debug Mapping Endpoints (OWUI ↔ Retriva)

This SDD defines **debug-only endpoints** for inspecting internal identifier mappings between **Open WebUI (OWUI)** and **Retriva**. These endpoints are intended strictly for **development, debugging, and operational troubleshooting** and must not be exposed as part of the public or stable API surface.

The goal is to make otherwise opaque integration state **observable and verifiable** without changing runtime behavior.

---

## Motivation

Retriva integrates with Open WebUI through a Thin Adapter that:
- maps OWUI Knowledge Bases to Retriva `kb_id`s
- maps OWUI uploaded documents/files to Retriva `doc_id`s

These mappings are persisted internally (e.g., SQLite mapping store) and are critical for:
- debugging ingestion issues
- validating KB routing
- diagnosing retrieval mismatches
- ensuring correct deletion and re-ingestion behavior

---

## Design Principles

- **Read-only**: debug endpoints must never mutate state
- **Explicitly non-public**: exposed under `/internal/...`
- **Disabled by default**: gated by configuration flag
- **Adapter-owned**: implemented in the Thin Adapter, not OWUI
- **Transparent**: reflect actual persisted state, not inferred state

---

## Configuration Gate (Mandatory)

Debug endpoints MUST be disabled unless explicitly enabled.

```env
ENABLE_DEBUG_ENDPOINTS=true
```

If disabled, all debug endpoints must return `404 Not Found`.

---

## Debug Endpoints Overview

### 1. Knowledge Base Mapping Inspection

```
GET /internal/mappings/knowledge-bases
```

Returns the current mapping between OWUI Knowledge Bases and Retriva Knowledge Bases.

### 2. Document / File Mapping Inspection

```
GET /internal/mappings/documents
```

Returns the mapping between OWUI uploaded files and Retriva documents.

### 3. Single Document Lookup (Optional)

```
GET /internal/mappings/documents/{owui_file_id}
```

---

## Acceptance Criteria

- Debug endpoints return correct, up-to-date mappings
- Endpoints are unreachable when `ENABLE_DEBUG_ENDPOINTS` is false
- No impact on ingestion or retrieval behavior

---

## Summary

These debug endpoints provide **critical observability** into the OWUI ↔ Retriva integration layer. They are intentionally minimal, gated, and read-only.