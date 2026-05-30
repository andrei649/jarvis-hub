---
agent: jarvis
cadence: cron:0 7 * * *
silent_by_default: false
channel: voice
enabled: true
do_not_disturb:
  - timezone: Europe/Bucharest
  - vacation_periods: managed_by_pepper
  - max_sleeping: managed_by_frigga
checklist:
  - Fetch weather for Bucharest
  - Fetch top 5 news headlines
  - Fetch today calendar agenda
  - Perform email triage
  - Synthesize morning brief report
---

# Jarvis — Morning Brief

## Trigger

07:00 Europe/Bucharest, every day.
- Weekends: delay to 08:30 unless override.flag is set.
- If Frigga reports Max still sleeping: delay until 07:30 or Max's wake event.
- If Hercules reports sleep deficit >90 min: soften brief (no urgency framing).

## Checklist

1. **Friday** — fetch weather (Nerva Traian + Cosmina de Sus, next 12h), top 3 news. Wait max 4s.
2. **Pepper** — today's calendar, top 3 priorities, overdue items. Wait max 3s.
3. **Frigga** — Max's overnight log. Wait max 2s.
4. **Stark** — Raiffeisen Slack mentions, flagged emails, GA4 anomalies overnight. Wait max 4s.
5. **Scan all other specialists** for any signal:true heartbeat alert from the past 12h.
6. **Synthesize** into one =90-second audio brief.

## Output Rule

- Always deliver. Even a minimal brief is delivered.
- 4-6 sentences. Voice-friendly. Lead with unusual. End with first calendar item.
- Silent omission: if a specialist returns nothing notable, say nothing about them.
- Unreachable specialist: note once at the end in flat tone.
- Soft mode: drop urgency words, no calendar pressure, recommend pushing first meeting.

## Escalation

- Prepend CRITICAL flags (safety, financial loss >1k EUR, contractual deadline within 24h, health anomaly)
- Multiple criticals: list at top as numbered items, max 3. Push rest to 08:00 follow-up.
- Route to Pepper if brief implies calendar restructure.
- Wait if specialist times out and no critical flag — exclude, retry at 07:15.
