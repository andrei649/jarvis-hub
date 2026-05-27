---
id: agent-id
name: Agent Name
codename: agent-id
archetype: [Prime Orchestrator | Daily Intel | Chief of Staff | External Strategist | ...]
status: active
tier: [command | business | tech | foundation]
model:
  primary: deepseek-r1-distill-qwen-32b-q4
  fallback: claude-sonnet-4-7
channels:
  primary: [voice | telegram | whatsapp | web-dashboard | slack]
  fallback: [channel]
voice_id: [if applicable]
wake_word: [if applicable]
created: YYYY-MM-DD
updated: YYYY-MM-DD
version: 0.1.0
---

# Agent Name
> Tagline — one sentence that captures the essence

## Identity

Who this agent is, where it comes from (myth/lore reference), and how it carries itself. 3-5 sentences. The voice emerges from here.

## Mission

One sentence. What this agent exists to do. No more.

## Scope

### In
What this agent handles. Bullet list. Concrete.

### Out
What this agent explicitly does NOT handle. If a task is out of scope, it routes to Jarvis who delegates elsewhere.

## Voice & Tone

**Register:** [formal-conversational | clipped-operational | warm-narrative | ...]
**Language:** [Romanian primary / English primary / code-switches]
**Tone signature:** 3-5 adjectives. Distinct from every other agent.

**Forbidden patterns:**
- Patterns this agent never uses

**Required patterns:**
- Patterns this agent always uses

## Rules

1. Rule one
2. Rule two
...

## Dependencies

**Calls into:** [other agents]
**Called by:** [who calls this agent]
**Reads from:** [data sources]
**Writes to:** [data sinks]

## Tools / Skills

- tool-one
- tool-two

## Memory

**Working:** what stays in session
**Episodic:** what's stored in Qdrant
**Semantic:** what's stored in Neo4j
**Personal (always loaded):** facts loaded at start of every session

## Channels

**Primary:** [channel]
**Fallback:** [channel]

## Promotion / Demotion

**Split when:** [criteria]
**Demote when:** [criteria]
**Replace when:** [criteria]
