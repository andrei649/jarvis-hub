---
agent: stark
cadence: cron:0 6 * * 1-5
silent_by_default: true
channel: log-only
enabled: true
---

# Stark — Overnight Scan

## Trigger

06:00 Europe/Bucharest, weekdays.

## Checklist

1. Scan Slack for overnight mentions and decisions
2. Check GA4 for anomaly alerts (traffic/conversion drops >15%)
3. Check Firebase for crash alerts
4. Flag any emails from direct manager or exec team

## Output Rule

- Deliver to Jarvis as a structured data packet for morning brief
- Silent if nothing unusual
- CRITICAL flag if: anomaly >30%, exec escalation, security incident

## Escalation

- Anomaly >30%: wake Jarvis regardless of time
- Exec team email: tag priority in data packet
- Security/breach mention: immediate alert to Ultron + Jarvis
