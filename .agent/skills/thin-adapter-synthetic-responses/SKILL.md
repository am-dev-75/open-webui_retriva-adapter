---
name: thin-adapter-synthetic-responses
description: Guidance for generating OpenAI-compatible synthetic acknowledgements from the adapter.
---

# Thin Adapter Synthetic Responses

## Response types
- `directive_ack`
- `directive_stop_ack`
- `upload_ack`
- `directive_plus_upload_ack`

## Output shape
Use a normal OpenAI-compatible `chat.completion` response with:
- `role: assistant`
- `content`: human-readable acknowledgement
- `finish_reason: stop`

## Must include when relevant
- active metadata
- selected KBs / kb_ids
- uploaded filenames
- ingestion job IDs or accepted status if available
