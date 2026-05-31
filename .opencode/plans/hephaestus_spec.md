# SPECIFICATION: Hephaestus (Hephaestus)

## Identity
- **Name:** Hephaestus
- **Archetype:** Builder And Mechanic
- **Tier:** foundation
- **Role:** Foundation & Personal
- **Heartbeat:** 2h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- none

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 2h
- Intent match via router keywords in gents/core/router.py