# SPECIFICATION: Stark (Stark)

## Identity
- **Name:** Stark
- **Archetype:** Biz Intel
- **Tier:** business
- **Role:** Business & Intelligence
- **Heartbeat:** 4h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- gmail

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 4h
- Intent match via router keywords in gents/core/router.py