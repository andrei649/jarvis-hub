# SPECIFICATION: Steve (Steve)

## Identity
- **Name:** Steve
- **Archetype:** CTO Plus Builds
- **Tier:** tech
- **Role:** Tech & Infrastructure
- **Heartbeat:** 1h
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
- Heartbeat every 1h
- Intent match via router keywords in gents/core/router.py