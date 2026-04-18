---
name: thin-adapter-patterns
description: Design patterns for upload mirroring adapters.
---

# Thin Adapter Patterns

## Core idea
Observe → Mirror → Map → Clean up

## Responsibilities
- detect uploaded files
- fetch file content
- call Retriva ingestion
- store mapping (file_id ↔ doc_id)
- propagate deletions

## Non-responsibilities
- retrieval
- embedding
- UI logic
