# SPECIFICATION: Veronica (Veronica)

## Identity
- **Name:** Veronica
- **Archetype:** Content Plus Comms
- **Tier:** business
- **Role:** Business & Intelligence
- **Heartbeat:** no
- **LLM Policy:** cloud-optional

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- cloud-llm

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every N/A — on-demand only
- Intent match via router keywords in gents/core/router.py