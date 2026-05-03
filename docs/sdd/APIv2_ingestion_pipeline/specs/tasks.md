# Implementation Tasks
1. **Configuration**: Add `RETRIVA_INGESTION_API_VERSION` (default: v1) to config/settings.
2. **Client Abstraction**: Create a base `RetrivaClient` with `RetrivaClientV1` and `RetrivaClientV2` implementations.
3. **v2 Client**: Implement the v2 client targeting `/api/v2/documents`. Map OWUI tags to `user_metadata`.
4. **Sync Logic**: Update the sync reconciliation loop to use the active client version.
