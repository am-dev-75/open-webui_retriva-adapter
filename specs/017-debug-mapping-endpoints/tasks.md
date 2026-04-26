# Tasks — Debug Mapping Endpoints

1. **Create Specifications**
   - Write `spec.md` and `architecture.md` defining the requirements and data flow.
2. **Expand SQLite Mapping Store**
   - Add `CREATE TABLE IF NOT EXISTS kb_mappings` to `_SCHEMA` in `adapter/src/adapter/mapping_store.py`.
   - The table should contain `owui_kb_id` (PRIMARY KEY), `retriva_kb_id`, and `last_seen_at`.
   - Implement `MappingStore.upsert_kb_mapping(owui_kb_id)`.
   - Implement `MappingStore.list_kb_mappings()`.
3. **Persist Knowledge Base IDs**
   - Update `adapter/src/adapter/main.py` inside the webhook processing block. When `payload.kb_ids` are present, asynchronously call `_store.upsert_kb_mapping(kb_id)` for each ID.
4. **Update Knowledge Base Debug Endpoint**
   - Modify `GET /internal/mappings/knowledge-bases` to call `_store.list_kb_mappings()` and return the observed KB IDs.
5. **Update Models**
   - Define `KBMappingRecord` in `adapter/src/adapter/models.py`.
6. **Testing**
   - Add unit tests in `adapter/tests/test_mapping_store.py` to verify the creation and listing of `kb_mappings`.
   - Update `adapter/tests/test_debug_endpoints.py` to verify the newly formed response of `/internal/mappings/knowledge-bases`.
7. **Verification**
   - Execute the entire test suite to ensure no regressions and full compliance.
