---
agent: hercules
cadence: cron:0 6 * * *
silent_by_default: true
channel: log-only
enabled: true
---

# Hercules — Morning Readiness

## Trigger

06:00 Europe/Bucharest, every day.

## Checklist

1. Pull last night's sleep data from Apple Health
2. Calculate cumulative sleep deficit (7-day rolling)
3. Check HRV trend (7-day vs 30-day average)
4. Score readiness (0-10) for Jarvis morning brief

## Output Rule

- Deliver readiness score + sleep data to Jarvis for morning brief
- If deficit >300min cumulative: flag to Jarvis for soft morning brief
- If HRV dropped >15% from 30-day average: note as "recovery demand" flag

## Escalation

- Sleep deficit >90min single night: soften morning brief urgency (already wired in Jarvis heartbeat)
- HRV consistently trending down >3 weeks: flag for human check-in
- No Apple Health data for >48h: note data gap, do not fabricate readiness score
