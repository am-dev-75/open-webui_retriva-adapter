# Feature Spec — Retrieval Configuration via OWUI Control Panel

## Goal
Enable users to tune retrieval behavior (precision vs. recall) directly from the Open WebUI control panel by reinterpreting standard generation parameters as retrieval controls.

## Background
Open WebUI provides sliders for `temperature`, `top_p`, and sometimes `top_k` (when supported by the model). In a RAG context, these parameters are often better utilized as retrieval parameters rather than just generation parameters.

## In scope
- Intercepting `top_k`, `top_p`, and `temperature` in the Thin Adapter.
- Reinterpreting these parameters as retrieval controls.
- Selective forwarding: only for turns classified as substantive human questions.
- Stripping parameters from the top-level request body to prevent interference with backend generation defaults.

## Out of scope
- Implementation of the retrieval logic in Retriva (Backend responsibility).
- New UI elements in Open WebUI.

## Functional requirements

### FR1 — Parameter Extraction
The adapter shall extract `top_k`, `top_p`, and `temperature` from the incoming OpenAI-compatible request body.

### FR2 — Semantic Reinterpretation
The extracted parameters shall be moved into a `retrieval` object within the request body.

### FR3 — Contextual Forwarding
The `retrieval` object shall only be included when forwarding a request to Retriva for a "real user question" (human-authored, substantive text).

### FR4 — Interception Neutrality
Turns intercepted by the adapter (directives-only, upload-only) shall not forward or apply these parameters.

### FR5 — Control-Plane Prompt Exclusion
OWUI internal control prompts (e.g., chat history analysis, title generation) shall be treated as non-human turns and shall not trigger retrieval parameter forwarding.
