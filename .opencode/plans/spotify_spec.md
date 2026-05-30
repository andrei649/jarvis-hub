# SPECIFICATION: H2.5 Jerome Spotify Skill

## 1. Context & Architecture Goal
The Jerome Spotify Skill enables JARVIS to control audio playback via the Spotify Web API. It must be exposed as a modular plugin compatible with the `plugin_gate.py` manifest registry and orchestrated by `orchestrator.py` via asynchronous event loops.

## 2. Technical Stack Requirements
- **Module Path**: `agents/core/skills/spotify.py`
- **HTTP client**: `httpx.AsyncClient` (for upstream Spotify API requests).
- **Async Framework**: FastAPI endpoints communicating via `asyncio`.
- **Authentication**: OAuth2 Bearer token routing injected from external secrets (`.env`).

## 3. API Endpoints & Request/Response Contracts
All endpoints must be mounted on the FastAPI application under the `/api/skills/spotify` prefix.

### A. POST `/api/skills/spotify/play`
Starts or resumes playback. Optional `context_uri` (album/playlist) or `uris` (tracks) can be provided in the payload.
- **Payload**:
```json
{
    "context_uri": "string",
    "uris": ["string"]
}
```
- **Success Response (200 OK)**: `{"status": "success", "message": "Playback started"}`
- **Error Response (404 Not Found)**: `{"detail": "No active device found"}`

### B. POST `/api/skills/spotify/pause`
Pauses current active playback.
- **Payload**: None
- **Success Response (200 OK)**: `{"status": "success", "message": "Playback paused"}`

### C. POST `/api/skills/spotify/skip`
Skips to the next track in the user's queue.
- **Payload**: None
- **Success Response (200 OK)**: `{"status": "success", "message": "Track skipped"}`

### D. POST `/api/skills/spotify/queue`
Adds a track URI to the user's active playback queue.
- **Payload**:
```json
{
    "uri": "string"
}
```
- **Success Response (200 OK)**: `{"status": "success", "message": "Track added to queue"}`

### E. GET `/api/skills/spotify/now_playing`
Retrieves information about the currently playing track and player state.
- **Success Response (200 OK)**:
```json
{
    "is_playing": true,
    "track_name": "string",
    "artist_name": "string",
    "progress_ms": 0,
    "duration_ms": 0
}
```
- **Fallback Response (204 No Content)**: Returns when no track is currently playing or player is inactive.

## 4. Failure Modes & Graceful Degradation
- **Spotify API Inaccessible**: If upstream returns 5xx or connection timeout, wrap it inside a custom domain handler and return a `502 Bad Gateway` with `{"detail": "Spotify service unavailable"}`. Do not crash the `orchestrator.py` lifecycle.
- **Expired Token**: Intercept 401 Unauthorized from Spotify, trigger a mock token refresh sequence internally, and retry the request once before throwing a state exception.
