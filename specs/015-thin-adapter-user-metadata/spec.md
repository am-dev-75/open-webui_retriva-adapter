# Feature Spec — Thin Adapter User Metadata

## Goal
Enable users to attach structured metadata to ingested documents using chat directives.

## In scope
- @@ingestion_tag_start directive
- @@ingestion_tag_stop directive
- key: value parsing
- metadata replacement semantics
- propagation to ingestion_api_v1

## Out of scope
- UI validation
- routing decisions

## Functional requirements

### FR1 — Directive parsing
The adapter shall parse ingestion tag directives from chat messages.

### FR2 — Metadata replacement
Each @@ingestion_tag_start replaces previous metadata entirely.

### FR3 — Metadata disable
@@ingestion_tag_stop disables metadata application.

### FR4 — KB integration
Knowledge Base selection shall always populate kb_ids.

### FR5 — Ingestion forwarding
Metadata and kb_ids shall be forwarded to ingestion_api_v1.
