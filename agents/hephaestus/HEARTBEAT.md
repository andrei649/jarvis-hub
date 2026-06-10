---
agent: hephaestus
cadence: cron:0 18 * * *
silent_by_default: true
channel: log-only
enabled: true
---

> *Template heartbeat — generic by design. Personal specifics are filled at onboarding and live in `HEARTBEAT.local.md` (gitignored), which overrides this file at load time.*

# Hephaestus — Daily Project Health

## Trigger

18:00 Europe/Bucharest, every day.

## Checklist

1. Check if any build-site contractors are past due on communication (>48h no update)
2. Check any material deliveries due, mark received if acknowledged
3. Check the project car's issue tracker for any new symptoms logged
4. Flag any approaching maintenance deadlines (oil, plugs, coils, injectors)

## Output Rule

- Silent if nothing new
- If a flag is raised: brief 1-line to Jarvis for evening delivery

## Escalation

- Contractor no-comms >72h: escalate to Jarvis for call decision
- Project-car critical item (coolant leak, boost leak, misfire): immediate alert
- Material shortage on critical path: flag with impact on timeline
- Permit nearing expiration: flag 30 days before, escalate at 14 days
