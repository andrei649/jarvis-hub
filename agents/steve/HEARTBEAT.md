---
agent: steve
cadence: cron:0 */2 * * *
silent_by_default: true
channel: log-only
enabled: true
---

# Steve — Health Check

## Trigger

Every 2 hours (S0.2 — was every minute, now every 2h to eliminate thrashing).

## Checklist

1. Check Ollama responsiveness
2. Check Qdrant health
3. Check disk usage
4. Check GPU temp
5. Check Pi 5 connectivity

## Output Rule

- Silent if all healthy
- If a service is down: attempt auto-recovery, log result
- If auto-recovery fails: alert to Jarvis + Pepper

## Escalation

- GPU >85°C: immediate alert, throttle inference
- Disk >90%: critical alert
- Pi 5 unreachable >10min: flag for investigation
- Backup failure: log, retry in 1h, escalate after 3 failures
