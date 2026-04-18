# SDD Pack — Thin Adapter (Pattern B-1)

This pack adds a **Python-based thin adapter** that mirrors file uploads from Open WebUI into Retriva.

The adapter allows users to keep using the native Open WebUI "+" upload button while ensuring that:
- Open WebUI does not perform retrieval
- Retriva owns ingestion, chunking, embeddings, and deletion
