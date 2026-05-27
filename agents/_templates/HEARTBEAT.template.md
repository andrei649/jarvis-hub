---
agent: agent-id
cadence: cron:* * * * *
silent_by_default: true
channel: [voice | telegram | slack | log-only]
enabled: true
do_not_disturb:
  - timezone: Europe/Bucharest
  - vacation_periods: managed_by_pepper
---

# Agent Name — Heartbeat [name]

## Trigger

When this heartbeat fires. Format: cron expression or event description.

## Checklist

1. Step one
2. Step two
...

## Output Rule

- What to surface vs what to suppress
- Format expected

## Escalation

- When to escalate to Jarvis
- When to flag as CRITICAL
- When to stay silent

## Example Cycle

> "Example heartbeat output"

## Related Heartbeats

- Links to other heartbeats in the same chain
