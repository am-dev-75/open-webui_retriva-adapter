# UX Routing Guidelines for the Thin Adapter

## Desired behavior
- Directive-only turns should produce acknowledgement, not “I do not have sufficient evidence...”
- Upload-only turns should produce ingestion confirmation, not “It appears that no specific question was provided..."
- Only turns with real questions should invoke the chat LLM

## Synthetic acknowledgement examples

### Directive start
Ingestion tagging enabled.

Active metadata:
- topic: cybersecurity
- keyword: CRA

This metadata will be attached to subsequent uploaded documents until `@@ingestion_tag_stop` is received.

### Directive stop
Ingestion tagging disabled.

Subsequent uploaded documents will no longer receive user-provided metadata.

### Upload only
Documents received and forwarded for ingestion.

Files:
- CRA Gids v2.0....pdf

Knowledge bases:
- R&D

Active user metadata:
- topic: cybersecurity
- keyword: CRA
