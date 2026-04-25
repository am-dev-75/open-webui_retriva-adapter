---
name: thin-adapter-turn-classification
description: Guidance for classifying user turns into directive, upload, or question flows.
---

# Thin Adapter Turn Classification

## Turn signals
- `has_directive`: one or more ingestion directives are present
- `has_files`: one or more file uploads are present
- `has_substantive_question`: remaining user text contains a meaningful natural-language request after stripping directives and upload-only artifacts

## Routing rules
1. directive only -> synthetic directive acknowledgement
2. upload only -> synthetic upload acknowledgement
3. directive + upload, no question -> synthetic combined acknowledgement
4. any turn with a substantive question -> process directives/uploads first, then forward to chat LLM

## Guardrails
- directive parsing must not leak into user-visible LLM prompts
- acknowledgements must be deterministic and generated locally
