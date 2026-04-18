---
description: Constitution for Thin Adapter (Pattern B-1)
alwaysApply: true
---

# Retriva Constitution — Thin Adapter

## Product law
- Retriva remains the single source of truth for RAG
- Open WebUI remains a pure UX client
- The adapter mirrors file lifecycle only

## Architecture law
- No forks of Open WebUI
- Adapter communicates only through public APIs
- Adapter failures must not break chat UX

## Scope law
Out of scope:
- replacing Open WebUI Knowledge UI
- direct vector manipulation
- modifying Open WebUI internals
