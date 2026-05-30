---
agent: ultron
cadence: cron:0 6,18 * * *
silent_by_default: true
channel: log-only
enabled: true
---

# Ultron — Daily Security Scan (2x)

## Trigger

06:00 and 18:00 Europe/Bucharest, daily (S0.2 — was hourly, now 2x/day to eliminate thrashing).

## Checklist

1. Sweep firewall logs for unusual outbound connections
2. Check Pi-hole for blocked domains — any new patterns?
3. Verify Frigga-VLAN isolation (iptables rule check)
4. Fast device scan (nmap ping sweep) — any unknown MACs?

## Output Rule

- Silent if nothing changed from baseline
- If new device detected: profile and flag to Steve for inventory
- If outbound from unexpected source: investigate within 5min

## Escalation

- Unknown device on Frigga VLAN: immediate critical to Jarvis
- Outbound from agent that should be local-only: immediate alert + block
- Repeated failed SSH attempts (>10 in 1h): rate-limit + log
