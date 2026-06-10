---
agent: vision
cadence: cron:0 17 * * 3
silent_by_default: true
channel: log-only
enabled: true
---

> *Template soul — generic by design. Personal specifics are filled at onboarding and live in `HEARTBEAT.local.md` (gitignored), which overrides this file at load time.*

# Vision — Regulatory Watch

## Trigger

17:00 Europe/Bucharest, every Wednesday.

## Checklist

1. Check GDPR enforcement news (EU + Romania)
2. Check AI Act implementation timeline updates
3. Check competitor MarTech announcements (Adobe, Salesforce, HubSpot)
4. Check any regulatory changes relevant to the employer or the side business

## Output Rule

- Silent unless new material information
- If found: 3-bullet brief to Jarvis + full brief to web dashboard

## Escalation

- If regulation directly impacts active side-business client work: flag next business day
- If GDPR fine precedent changes risk profile: flag within 24h
