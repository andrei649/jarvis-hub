---
agent: friday
cadence: cron:30 6 * * *
silent_by_default: true
channel: log-only
enabled: true
---

# Friday — Pre-Dawn Collection

## Trigger

06:30 Europe/Bucharest, every day.

## Checklist

1. Fetch weather for Nerva Traian + Cosmina de Sus — next 12h
2. Fetch top 3 from each RSS feed (tech, banking, CRM)
3. Check market data if trading day
4. Check traffic (weekday only)
5. Write to state/friday/morning-brief.json for Jarvis to consume

## Output Rule

- Never surface to Andrei directly. Data is consumed by Jarvis.
- Time budget: 25s total. If a source hangs >4s, skip.
- Flag repeats: "same as yesterday, delta: +2°C"

## Escalation

- If all sources fail: write empty brief and flag staledata to Jarvis
- Any single source failure: silently omit and continue
