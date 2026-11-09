# Calendar

> Pepper's Google Calendar — read today's agenda, create events, check availability

**Version:** 0.2.0
**Author:** claude
**Agents:** pepper

## Usage
Wraps `GoogleCalendarPlugin`. Requires `GOOGLE_CALENDAR_TOKEN` in `.env`.
Degrades gracefully with a clear message when no credentials are present.

## Commands
- `today <input>` — list today's events
- `add_event <input>` — create an event: `<title>|<start ISO>|<end ISO>`
- `free <input>` — "am I free [tomorrow at 3pm]?" / "când sunt liber?". With a
  concrete time → yes/no via `am_i_free`. Without one → lists the day's remaining
  free slots (today by default). Understands today/tomorrow/azi/mâine + an hour
  (`3pm`, `15:30`, `la 3`).

## Example Output
```
Agenda de azi (2):
- 10:00 Standup
- 14:00 Review Q2
Eveniment creat: „Meeting” (2026-06-01T10:00 – 2026-06-01T11:00). [abc123]
Da, ești liber pe 21 Jun 15:00.
Sloturi libere azi (3):
- 11:00–11:30
- 11:30–12:00
- 16:00–16:30
```
