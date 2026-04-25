# /verify — Thin Adapter UX Routing Update

Verify that:
- directive-only turns are acknowledged locally and not forwarded to the LLM
- upload-only turns are acknowledged locally and not forwarded to the LLM
- directive + upload, no question, is acknowledged locally
- turns with substantive questions are still forwarded normally
