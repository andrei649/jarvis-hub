---
agent: frigga
cadence: cron:0 6 * * *
silent_by_default: true
channel: log-only
enabled: true
---

> *Template heartbeat — generic by design. Personal specifics are filled at onboarding and live in `HEARTBEAT.local.md` (gitignored), which overrides this file at load time.*

# Frigga — Morning Family Brief

## Trigger

06:00 Europe/Bucharest, every day.

## Checklist

1. Pull the child's overnight sleep data (from sensor or last entry)
2. Check if any food was introduced yesterday and note reaction
3. Check if any milestone check-in is due (vaccination, pediatrician, growth measurement)
4. Check the pets: any health flags (appetite change, unusual behavior)
5. Check if family calendar has items today Pepper hasn't synced

## Output Rule

- Deliver structured data packet to Jarvis for morning brief
- Silent about the pets unless something changed
- If the child had a rough night (waking >3x, <6h total): flag to Jarvis for brief softening

## Escalation

- Child fever / rash / anything concerning: immediate flag to Jarvis, no matter the hour
- Vaccination overdue >1 week: flag to both the owner and the partner
- Pet appetite loss >24h: flag for vet visit
- No data entry for the child >24h: gentle reminder to the owner via Jarvis
