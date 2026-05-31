# SPECIFICATION: Oracle (Oracle)

## Identity
- **Name:** Oracle
- **Archetype:** N8N Workflows
- **Tier:** tech
- **Role:** Tech & Infrastructure
- **Heartbeat:** no
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
- Heartbeat every N/A — on-demand only
- Intent match via router keywords in gents/core/router.py