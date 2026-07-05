# H18.14 Mobile Status Ambient Dashboard + Ticker Design

## Goal

Bring two read-only browser HUD surfaces to the native mobile Status tab:
`GET /dashboard` ambient dashboard data and `GET /ticker` live situation
ticker data.

## Non-goals

- No new backend routes.
- No mobile write actions.
- No new bottom navigation tab.
- No invented/demo rows when the hub returns empty payloads.

## Approach

The existing `StatusScreen` already answers "is my hub alive?" with `/status`.
H18.14 extends that same screen with two compact cards:

- `Today`: weather, calendar count, and notification count from `/dashboard`.
- `Ticker`: current agent activity/warnings from `/ticker`.

Both calls are optional companions to `/status`. If `/status` fails, the screen
still shows the existing connection error. If dashboard/ticker data is sparse or
unavailable, the new cards render honest empty states instead of blocking the
core status view.

## Data Contracts

Mobile client additions live in `mobile/src/api/client.ts`:

- `fetchDashboard(config): Promise<DashboardResponse>`
- `fetchTicker(config): Promise<TickerResponse>`

The client normalizes sparse payloads to stable arrays:

- `calendar: []`
- `notifications: []`
- `weather: undefined` when absent or malformed
- `ticker: []`

Ticker rows normalize display fields so the UI can stay simple:

- `text` is `text || obj || ""`
- `bar` is `bar ?? pct ?? 0`
- `cls` is `cls || pri || ""`

## Risks

The dashboard weather object is plugin-shaped and may be sparse. The mobile
client treats the weather block as optional and leaves details blank rather than
making strong assumptions. This keeps the phone honest across owner setups.

## Verification

- Mobile API Jest tests prove request paths, user-token auth, and sparse-payload
  normalization.
- Mobile TypeScript verifies the Status screen and client types.
- `scripts/status_sync.py --check` verifies docs/status counters stay aligned.
