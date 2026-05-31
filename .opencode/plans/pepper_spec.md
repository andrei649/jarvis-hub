# SPECIFICATION: Pepper (Pepper)

## Identity
- **Name:** Pepper
- **Archetype:** Chief of Staff
- **Tier:** command
- **Role:** Orchestration & Operations
- **Heartbeat:** 2h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- google-calendar
- gmail
- telegram

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 2h
- Intent match via router keywords in gents/core/router.py