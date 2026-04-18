# SDD Pack — Thin Adapter (Pattern B-1)

**Status:** Final | **Version:** 1.0 | **Date:** 2026-04-18

---

## Summary

This pack adds a **Python-based thin adapter** (sidecar service) that mirrors
file uploads from Open WebUI into Retriva's ingestion pipeline.

The adapter allows users to keep using the native Open WebUI "+" upload
button while ensuring that:

- **Open WebUI does not perform retrieval** — Retriva owns RAG
- **Retriva owns ingestion, chunking, embeddings, and deletion**
- **File lifecycle is synchronized** — uploads mirror in, deletions mirror out

---

## Architecture Decision Records

### ADR-1: Polling over Webhooks

**Decision:** Use polling (`GET /api/v1/files`) instead of webhooks.

**Rationale:** Open WebUI does not expose lifecycle webhooks for file events.
Polling is the only non-invasive observation mechanism. The webhook approach
is deferred to roadmap v0.7+ pending upstream support.

### ADR-2: SQLite for Mapping Persistence

**Decision:** Use SQLite (with WAL mode) for the mapping database.

**Rationale:** The mapping volume is small (one row per file). SQLite is
zero-dependency, file-based, and trivially backed up via volume snapshots.
PostgreSQL would add operational complexity with no benefit at this scale.

### ADR-3: FastAPI for the Service Shell

**Decision:** Use FastAPI for health, metrics, and admin endpoints.

**Rationale:** Async-native, lightweight, generates OpenAPI docs automatically.
Aligns with the Retriva tech stack.

### ADR-4: Adapter as a Sidecar, Not a Plugin

**Decision:** Deploy the adapter as a standalone container, not an Open WebUI
plugin or pipeline.

**Rationale:** The non-negotiable rule is "do not modify Open WebUI". A
sidecar communicating only via public APIs satisfies this constraint and can
be independently versioned, deployed, and replaced.

---

## Spec Pack Contents

| Document | Path | Description |
|---|---|---|
| Feature Spec | `specs/012-…/spec.md` | Goals, scope, API contracts, config model |
| Architecture | `specs/012-…/architecture.md` | Components, data flow, failure handling, deployment |
| Acceptance | `specs/012-…/acceptance.md` | Given/When/Then criteria with verification matrix |
| Tasks | `specs/012-…/tasks.md` | 31 numbered tasks across 7 phases |
| Plan | `specs/012-…/plan.md` | Phased implementation plan with exit criteria |

---

## API Surface Summary

### Consumed (upstream)

| System | Endpoint | Purpose |
|---|---|---|
| Open WebUI | `GET /api/v1/files` | Discover uploaded files |
| Open WebUI | `GET /api/v1/files/{id}/content` | Download file bytes |
| Retriva | `POST /api/v1/ingest` | Forward file for ingestion |
| Retriva | `DELETE /api/v1/documents/{doc_id}` | Remove ingested document |

### Exposed (adapter)

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Liveness probe |
| `/readyz` | GET | Readiness probe (checks upstreams) |
| `/metrics` | GET | Prometheus metrics |
| `/api/v1/sync` | POST | Force immediate sync cycle |
| `/api/v1/mappings` | GET | List file↔document mappings |
