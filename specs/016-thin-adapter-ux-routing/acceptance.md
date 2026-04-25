# Acceptance Criteria — Thin Adapter UX Routing Update

- Directive-only turns produce a local acknowledgement and are not forwarded to the chat LLM.
- Upload-only turns produce a local acknowledgement and are not forwarded to the chat LLM.
- Directive + upload turns without a real question produce a combined acknowledgement.
- Turns containing a substantive question are still forwarded normally after ingestion-side processing.
- Synthetic replies are valid OpenAI-compatible responses.
