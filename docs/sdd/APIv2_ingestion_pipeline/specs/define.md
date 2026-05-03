# Define: Adapter API v2 Migration
**Goal**: Support configuring the adapter to use Retriva Core's v1 or v2 API via an environment variable `RETRIVA_INGESTION_API_VERSION`.
**Key Requirements**:
1. Ensure Open WebUI-facing endpoints remain 100% stable.
2. Propagate tags/metadata correctly to Core's `user_metadata` field when in v2 mode.
