# Architecture — Thin Adapter (Pattern B-1)

## High-level flow

Open WebUI → Adapter → Retriva

## Components
- FileObserver (polling or event-based)
- FileFetcher
- RetrivaClient
- MappingStore

## Data model
Mapping record:
- openwebui_file_id
- filename
- kb_id
- retriva_doc_id
- created_at

## Failure handling
- ingestion failures are retried
- adapter outages do not break chat
