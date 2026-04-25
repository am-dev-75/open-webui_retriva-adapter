# Architecture — Thin Adapter UX Routing Update

## Design principle
The Thin Adapter becomes the authoritative classifier of ingestion-related turns before any request is forwarded to the chat LLM.

## Turn model
For every user turn, compute:
- `has_directive`
- `has_files`
- `has_substantive_question`

## Routing table

1. `has_directive and not has_files and not has_substantive_question`
   - update ingestion context
   - return `directive_ack` or `directive_stop_ack`

2. `has_files and not has_directive and not has_substantive_question`
   - mirror uploads to Retriva ingestion
   - return `upload_ack`

3. `has_directive and has_files and not has_substantive_question`
   - update ingestion context
   - mirror uploads
   - return `directive_plus_upload_ack`

4. Any case with `has_substantive_question`
   - process directives/uploads as needed
   - forward resulting question turn to the chat LLM

## Synthetic response contract
The adapter emits a standard OpenAI-compatible `chat.completion` response payload, generated locally.
