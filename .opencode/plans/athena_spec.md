# SPECIFICATION: Athena (Athena)

## Identity
- **Name:** Athena
- **Archetype:** External Strategist
- **Tier:** business
- **Role:** Business & Intelligence
- **Heartbeat:** 6h
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
- Heartbeat every 6h
- Intent match via router keywords in gents/core/router.py