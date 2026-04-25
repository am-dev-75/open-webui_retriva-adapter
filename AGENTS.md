# Agent Instructions — Thin Adapter UX Routing Update

## Mission
Update the Thin Adapter so it provides **UX-aware routing** for directive-only and upload-only turns.

The adapter must:
- intercept directive-only messages and **not** forward them to the chat LLM
- return an immediate synthetic acknowledgement for directives
- intercept upload-only turns and **not** forward them to the chat LLM
- return an immediate synthetic acknowledgement for uploads
- only forward turns to the chat LLM when there is a **substantive user question**

## Order of authority
1. `specs/016-thin-adapter-ux-routing/spec.md`
2. `specs/016-thin-adapter-ux-routing/architecture.md`
3. `.agent/rules/retriva-constitution.md`
4. `specs/016-thin-adapter-ux-routing/tasks.md`

## Non-negotiable rules
- Do not modify Open WebUI source code
- Do not forward directive-only turns to the chat LLM
- Do not forward upload-only turns to the chat LLM
- Synthetic acknowledgements must be OpenAI-compatible responses
- Turns with substantive questions must still be forwarded normally
