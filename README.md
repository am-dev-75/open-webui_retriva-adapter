# Open WebUI to Retriva Adapter

**Thin sidecar that mirrors Open WebUI file uploads into Retriva.**

The adapter polls Open WebUI for file changes, downloads new files,
forwards them to Retriva for ingestion, and propagates deletions.
No modifications to Open WebUI or Retriva are required.

---

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual values
```

Required variables:

| Variable           | Example                                 |
| ------------------ | --------------------------------------- |
| `OWUI_BASE_URL`    | `http://localhost:3000`                 |
| `OWUI_API_KEY`     | `sk-...` (from OWUI Settings → Account) |
| `RETRIVA_BASE_URL` | `http://localhost:8400`                 |

### 2. Run with Docker Compose

```bash
docker compose up -d adapter
```

### 3. Run locally (development)

```bash
cd adapter
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

export OWUI_BASE_URL=http://localhost:3000
export OWUI_API_KEY=your-key
export RETRIVA_BASE_URL=http://localhost:8400

python -m adapter
```

---

## API Endpoints

| Endpoint           | Method | Description                             |
| ------------------ | ------ | --------------------------------------- |
| `/healthz`         | GET    | Liveness probe                          |
| `/readyz`          | GET    | Readiness probe (checks OWUI + Retriva) |
| `/metrics`         | GET    | Prometheus metrics                      |
| `/api/v1/sync`     | POST   | Force immediate sync cycle              |
| `/api/v1/mappings` | GET    | List all file ↔ document mappings       |

---

## Configuration Reference

| Variable                | Required | Default             | Description                 |
| ----------------------- | -------- | ------------------- | --------------------------- |
| `OWUI_BASE_URL`         | ✅        | —                   | Open WebUI base URL         |
| `OWUI_API_KEY`          | ✅        | —                   | Bearer token for OWUI API   |
| `RETRIVA_BASE_URL`      | ✅        | —                   | Retriva base URL            |
| `RETRIVA_API_KEY`       | ❌        | —                   | Optional Retriva auth token |
| `POLL_INTERVAL_SECONDS` | ❌        | `30`                | Polling interval            |
| `DB_PATH`               | ❌        | `./data/adapter.db` | SQLite database path        |
| `LOG_LEVEL`             | ❌        | `INFO`              | Logging level               |
| `ADAPTER_PORT`          | ❌        | `8500`              | HTTP server port            |

---

## How It Works

```
Open WebUI ──(poll)──► Adapter ──(ingest)──► Retriva
                          │
                    ┌─────┴─────┐
                    │  SQLite   │
                    │  Mappings │
                    └───────────┘
```

1. **Poll** — Adapter calls `GET /api/v1/files` on Open WebUI every N seconds
2. **Diff** — Compares OWUI file list against local mapping database
3. **Ingest** — Downloads new files and forwards them to Retriva
4. **Map** — Stores `owui_file_id ↔ retriva_doc_id` in SQLite
5. **Delete** — Files removed from OWUI trigger Retriva document deletion
6. **Retry** — Failed ingestions are retried on subsequent cycles

---

## Testing

```bash
cd adapter
source .venv/bin/activate
python -m pytest tests/ -v
```

---

## Troubleshooting

| Symptom                         | Cause                                 | Fix                                                     |
| ------------------------------- | ------------------------------------- | ------------------------------------------------------- |
| Adapter logs "OWUI unreachable" | Wrong `OWUI_BASE_URL` or network      | Verify URL and connectivity                             |
| Files not syncing               | Invalid `OWUI_API_KEY`                | Regenerate key in OWUI Settings → Account               |
| Duplicate ingestions            | Should not happen (UNIQUE constraint) | Check adapter logs for errors                           |
| Adapter crash on startup        | Missing required env vars             | Set `OWUI_BASE_URL`, `OWUI_API_KEY`, `RETRIVA_BASE_URL` |

---

## Architecture

See [`specs/012-thin-adapter-openwebui-retriva/architecture.md`](specs/012-thin-adapter-openwebui-retriva/architecture.md) for full component design.
