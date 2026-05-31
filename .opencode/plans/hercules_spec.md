# SPECIFICATION: Hercules (Hercules)

## Identity
- **Name:** Hercules
- **Archetype:** Fitness Plus Nutrition
- **Tier:** foundation
- **Role:** Foundation & Personal
- **Heartbeat:** 2h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- apple-health

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 2h
- Intent match via router keywords in gents/core/router.py