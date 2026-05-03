# Acceptance Criteria
1. **v1 Mode**: If `RETRIVA_INGESTION_API_VERSION=v1`, adapter calls `/api/v1/ingest/*`.
2. **v2 Mode**: If `RETRIVA_INGESTION_API_VERSION=v2`, adapter calls `/api/v2/documents`.
3. **Metadata Sync**: In v2 mode, OWUI file tags are successfully passed to Core via `user_metadata`.
