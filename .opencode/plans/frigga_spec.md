# SPECIFICATION: Frigga (Frigga)

## Identity
- **Name:** Frigga
- **Archetype:** Family Matriarch
- **Tier:** foundation
- **Role:** Foundation & Personal
- **Heartbeat:** 4h
- **LLM Policy:** local

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- whatsapp-bridge

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 4h
- Intent match via router keywords in gents/core/router.py