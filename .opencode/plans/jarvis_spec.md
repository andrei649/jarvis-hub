# SPECIFICATION: Jarvis (Jarvis)

## Identity
- **Name:** Jarvis
- **Archetype:** Prime Orchestrator
- **Tier:** command
- **Role:** Orchestration & Operations
- **Heartbeat:** 12h
- **LLM Policy:** cloud-optional

## Skills
- None currently — SOUL.md provides system prompt identity

## Plugins
- cloud-llm
- telegram

## Memory
- Conversation history in memory_logs/sessions/
- Context cache via ContextCache (GeminiBackend only)
- Learning records in memory_logs/learning/

## Triggers
- Heartbeat every 12h
- Intent match via router keywords in gents/core/router.py