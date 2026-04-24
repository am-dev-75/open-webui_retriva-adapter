# Agent Instructions — Thin Adapter User Metadata

## Mission
Extend the Thin Adapter (Open WebUI → Retriva) to support **user-provided ingestion metadata**
using chat directives combined with Knowledge Base selection.

The adapter must:
- parse @@ingestion_tag_start and @@ingestion_tag_stop directives from chat messages
- maintain a per-chat ingestion metadata context
- replace metadata on each new @@ingestion_tag_start
- disable metadata on @@ingestion_tag_stop
- always populate kb_ids based on selected Knowledge Bases (Pattern A)
- send user_metadata and kb_ids to ingestion_api_v1

## Order of authority
1. specs/015-thin-adapter-user-metadata/spec.md
2. specs/015-thin-adapter-user-metadata/architecture.md
3. .agent/rules/retriva-constitution.md
4. specs/015-thin-adapter-user-metadata/tasks.md

## Non-negotiable rules
- Do not modify Open WebUI source code
- Do not modify ingestion_api_v1 semantics beyond passing metadata
- Metadata replacement semantics must be respected
- Adapter logic must be deterministic and stateless across restarts
