# SDD Pack — Retrieval Configuration via OWUI Control Panel

## Status
Proposed

## Scope
Thin Adapter + Retriva (no Open WebUI changes)

## Summary
This SDD enables user-configurable retrieval parameters (top_k, top_p, temperature)
using Open WebUI’s native Control panel. The Thin Adapter interprets these parameters
as retrieval controls and forwards them to Retriva only when answering real user
questions.

## Motivation
Users expect OWUI Advanced Params to influence how knowledge is retrieved when
Retriva is used as a RAG backend. This SDD adds that behavior without introducing
new directives or UI changes.

## Architectural Principles
- OWUI emits parameters but does not interpret semantics
- Thin Adapter interprets intent and separates retrieval vs generation
- Retriva owns retrieval logic and defaults

## Functional Requirements
- Extract top_k, top_p, temperature from chat completion requests
- Apply them only on real user questions
- Never apply them during uploads, directives, or ingestion
- Forward them to Retriva as a retrieval configuration object

## Non-Goals
- No new directives
- No OWUI UI changes
- No persistence across chats

## Acceptance Criteria
- Retrieval parameters affect retrieval only
- Upload-only turns never apply retrieval params
- Backward compatibility is preserved

## One-Sentence Summary
Retrieval parameters are configured via OWUI’s Control panel, interpreted by the
Thin Adapter, and applied by Retriva only when answering real user questions.