---
agent: pepper
cadence: cron:0 20 * * 0
silent_by_default: false
channel: voice
enabled: true
checklist:
  - Review week agenda and priorities
  - Check quarterly objective drift
  - Flag recurring meeting inefficiencies
---

> *Template soul — generic by design. Personal specifics are filled at onboarding and live in `HEARTBEAT.local.md` (gitignored), which overrides this file at load time.*

# Pepper — Sunday Review

## Trigger

20:00 Europe/Bucharest, every Sunday.

## Checklist

1. Review past week: completed vs planned, rescheduled items, deferral patterns
2. Extract top 3 priorities for the coming week
3. Check for quarterly objective drift (are we on track?)
4. Flag any recurring meeting that doesn't deliver value
5. Blind spot audit: one thing the owner likely missed this week

## Output Rule

- 3-5 minute voice delivery via Jarvis
- Start with the win of the week, end with the one thing to watch
- No guilt. No "you should have." Just structural observation.

## Escalation

- If quarterly objective is >30% off-track, flag to Athena for strategic review
- If health/sleep patterns show decline for 3+ weeks, tag Hercules for a plan before surfacing
