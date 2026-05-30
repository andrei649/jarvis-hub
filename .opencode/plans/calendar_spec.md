# SPECIFICATION: H2.1 Pepper Calendar Skill

## 1. Context & Objective
The Pepper Calendar Skill manages Google Calendar events. It operates asynchronously within FastAPI and authenticates using OAuth tokens stored locally as JSON in `memory_logs/tokens/google_cal.json`.

## 2. API Endpoints
All endpoints are prefixed with `/api/skills/calendar`.

### A. GET `/api/skills/calendar/events`
Lists upcoming events.
- **Query Params**: `limit` (int, default 10)
- **Success Response (200 OK)**:
```json
[
    {"id": "ev1", "summary": "Meeting", "start": "2026-06-01T10:00:00Z", "end": "2026-06-01T11:00:00Z"}
]
```

### B. POST `/api/skills/calendar/events`
Creates a new calendar event.
- **Payload**: `{"summary": "string", "start": "string", "end": "string", "description": "string"}`
- **Success Response (201 Created)**: `{"status": "success", "event_id": "string"}`

### C. PUT `/api/skills/calendar/events/{event_id}`
Updates an existing event.
- **Success Response (200 OK)**: `{"status": "success", "message": "Event updated"}`

### D. DELETE `/api/skills/calendar/events/{event_id}`
Deletes an event.
- **Success Response (200 OK)**: `{"status": "success", "message": "Event deleted"}`

## 3. Token Security & Fallbacks
- If `memory_logs/tokens/google_cal.json` is missing or the token is unreadable, endpoints must fail gracefully with `401 Unauthorized` and payload `{"detail": "Google Calendar credentials missing"}`.
- Network timeouts to Google API must return `502 Bad Gateway` with `{"detail": "Google Calendar API unreachable"}`.
