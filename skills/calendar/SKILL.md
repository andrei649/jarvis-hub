# Calendar

> Pepper's Google Calendar — read today's agenda and create events

**Version:** 0.1.0
**Author:** claude
**Agents:** pepper

## Usage
Wraps `GoogleCalendarPlugin`. Requires `GOOGLE_CALENDAR_TOKEN` in `.env`.
Degrades gracefully with a clear message when no credentials are present.

## Commands
- `today <input>` — list today's events
- `add_event <input>` — create an event: `<title>|<start ISO>|<end ISO>`

## Example Output
```
Agenda de azi (2):
- 10:00 Standup
- 14:00 Review Q2
Eveniment creat: „Meeting” (2026-06-01T10:00 – 2026-06-01T11:00). [abc123]
```
