---
agent: gecko
cadence: cron:0 19 * * 5
silent_by_default: true
channel: log-only
enabled: true
---

> *Template heartbeat — generic by design. Personal specifics are filled at onboarding and live in `HEARTBEAT.local.md` (gitignored), which overrides this file at load time.*

# Gecko — Weekly Financial Snapshot

## Trigger

19:00 Europe/Bucharest, every Friday.

## Checklist

1. Pull current balances for all active accounts
2. Calculate weekly burn rate
3. Check the side business's runway
4. Note any large transactions (>500 RON or >100 EUR) not yet categorized

## Output Rule

- Silent if within normal ranges
- If burn rate changed >20% from weekly average: brief 2-line update to Jarvis
- If the side business's runway <3 months: flag to Jarvis (not Athena — Gecko does not advise, just informs)

## Escalation

- Account balance below threshold: flag (threshold configurable, default 1,000 RON)
- Unexpected large transaction (>2,000 RON uncategorized): flag
- Any account connection failure: note in log, retry in 1h
