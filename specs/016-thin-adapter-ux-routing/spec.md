# Feature Spec — Thin Adapter UX Routing Update

## Goal
Improve the Thin Adapter UX by intercepting directive-only and upload-only turns and returning immediate synthetic acknowledgements instead of forwarding those turns to the chat LLM.

## Background
The current behavior produces confusing assistant replies when the user sends ingestion directives or uploads documents without asking a substantive question.

## In scope
- turn classification using `has_directive`, `has_files`, and `has_substantive_question`
- local synthetic acknowledgement generation
- directive-only interception
- upload-only interception
- combined directive+upload acknowledgement when no question exists
- preserving normal LLM forwarding for substantive questions

## Out of scope
- changes to Open WebUI frontend behavior
- changes to ingestion_api_v1 semantics
- new retrieval logic

## Functional requirements

### FR1 — Directive-only interception
Directive-only turns shall not be forwarded to the chat LLM.

### FR2 — Upload-only interception
Upload-only turns shall not be forwarded to the chat LLM.

### FR3 — Combined acknowledgement
A turn containing directives and uploads but no substantive question shall produce one combined acknowledgement.

### FR4 — Normal forwarding for questions
If a turn contains a substantive question, the adapter shall process directives/uploads first and then forward the turn to the chat LLM.

### FR5 — OpenAI-compatible synthetic responses
Synthetic acknowledgements shall be emitted as valid OpenAI-compatible chat completion responses.

## Acceptance summary
The feature is accepted when directive-only and upload-only turns no longer generate irrelevant LLM answers and users receive explicit confirmations instead.
