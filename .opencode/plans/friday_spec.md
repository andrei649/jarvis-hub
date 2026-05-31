# SPECIFICATION: Friday (Friday)

## Identity
- **Name:** Friday
- **Archetype:** Daily Intel
- **Tier:** command
- **Role:** Orchestration & Operations
- **Heartbeat:** 6h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- telegram

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 6h
- Intent match via router keywords in gents/core/router.py