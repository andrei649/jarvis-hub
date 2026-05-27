---
agent: athena
cadence: cron:0 18 * * 5
silent_by_default: true
channel: log-only
enabled: true
---

# Athena — Weekly Market Scan

## Trigger

18:00 Europe/Bucharest, every Friday.

## Checklist

1. Scan MarTech job market in CEE (new CMO/Head of roles)
2. Check Digitaholic pipeline health (inbound vs closed last 2 weeks)
3. Note any rate changes in consultancy market
4. Update career scenario models if new data available

## Output Rule

- Silent unless something changed. No "no news" reports.
- If something changed: brief 3-bullet summary to Jarvis for Friday evening voice delivery.

## Escalation

- If a relevant CMO role opens: flag to Jarvis within 1h
- If Digitaholic pipeline dries >3 weeks with no inbound: flag for strategy session
- If market rates shifted >15%: flag for rate card review
