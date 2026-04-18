# Feature Spec — Thin Adapter (Pattern B-1)

## Goal
Enable Open WebUI native file uploads to be mirrored into Retriva ingestion **without modifying Open WebUI**.

## In scope
- detect uploaded files in Open WebUI
- fetch uploaded file contents
- call Retriva ingestion APIs
- persist file ↔ document mappings
- propagate deletions

## Out of scope
- UI changes
- retrieval logic
- embedding logic

## Acceptance summary
Users upload files in Open WebUI, and those files are ingested into Retriva and can later be deleted cleanly.
