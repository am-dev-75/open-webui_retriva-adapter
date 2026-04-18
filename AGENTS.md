# Agent Instructions — Thin Adapter (Pattern B-1)

## Mission
Implement **Pattern B-1 — Thin Adapter** to mirror file uploads from **Open WebUI** into **Retriva** without modifying Open WebUI.

The adapter:
- is written in **Python**
- observes Open WebUI file lifecycle events
- forwards uploaded files to Retriva ingestion APIs
- keeps file ↔ document mappings
- is designed to be containerized once stable

## Order of authority
1. `specs/012-thin-adapter-openwebui-retriva/spec.md`
2. `specs/012-thin-adapter-openwebui-retriva/architecture.md`
3. `.agent/rules/retriva-constitution.md`
4. `specs/012-thin-adapter-openwebui-retriva/tasks.md`

## Non-negotiable rules
- Do not modify Open WebUI source code
- Do not modify Retriva core semantics
- The adapter must be stateless except for durable mappings
- Open WebUI native RAG must be disabled at query time
- The adapter must be replaceable without downtime
