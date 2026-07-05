# Mobile ⇄ Browser parity ledger

The **bridge** that keeps the iOS/Android apps (`mobile/`) in sync with the browser HUD.
Both clients talk to the **same** HTTP API (`agents/web.py`), so "feature parity" is mostly a
question of *which hub surfaces the mobile app has caught up to*.

This file is the single source of truth for that gap. Backlog tasks for closing it live under
**`BACKLOG.md` → ORIZONT 18**.

## The sync rule (how the bridge works)

> When a browser/HUD change adds or modifies a **user-facing endpoint or capability**, in the
> *same* PR you must:
> 1. **Update this table** — add/flip the row for that surface (browser ✅, mobile state).
> 2. **If mobile lags**, open or update a parity task `H18.x` in `BACKLOG.md` so the work is tracked.
>
> This is also written into `AGENTS.md` ("Bridge browser↔mobil") so every assistant (Claude,
> opencode, Gemini, Antigravity) applies it. Net effect: **browser developments automatically
> become iOS/Android tasks** instead of silently drifting.

Legend — **mobile**: ✅ shipped · 🟡 partial · ⬜ not started · ➖ not applicable on mobile.

## Parity matrix

| Surface | API (agents/web.py) | Browser | Mobile | Task |
|---------|---------------------|:-------:|:------:|------|
| Chat (streaming) | `POST /chat/stream`, `POST /chat` | ✅ | ✅ | H18.1 |
| Chat history persistence | — (client-side) | ✅ | ✅ | H18.2 |
| Agent selection | `GET /api/agents`, `agent` param | ✅ | ✅ | H18.3 |
| Markdown rendering | — (client-side) | ✅ | ✅ | H18.4 |
| Status / telemetry | `GET /status` | ✅ | ✅ | H18.1 |
| Sessions (resume) | `GET /sessions`, `POST /sessions/resume` | ✅ | ✅ | H18.5 |
| Voice / TTS | `POST /tts` | ✅ | ✅ | H18.5 |
| Stream timeout / reconnect | — (client-side) | ✅ | ✅ | H18.6 |
| Dashboard (weather/news) | `GET /dashboard` | ✅ | ⬜ | — |
| Tasks board | `GET /tasks` | ✅ | ⬜ | — |
| Ticker | `GET /ticker` | ✅ | ⬜ | — |
| Skills browser | `GET /skills` | ✅ | ⬜ | — |
| Memory / notes | `GET /memory`, `GET /api/notes` | ✅ | ⬜ | — |
| Knowledge graph | `GET /api/kg/*` | ✅ | ⬜ | — |
| Action approval queue | `GET /autonomy/approvals`, `POST /autonomy/tasks/{id}/decision` | ✅ | ✅ | H18.11 / O26-P3.4 |
| Channel inbox + governed replies | `GET /api/channels/inbox*`, `POST /api/channels/inbox/{thread_id}/reply` | ✅ | ⬜ | H18.12 |
| Chat rooms (multi-agent) | `GET/POST /api/rooms*` | ✅ | ⬜ | — |
| Arena / review / quality | `GET /api/arena/*`, `/api/review/*` | ✅ | ➖ | — |
| Security posture | `GET /api/security/*` | ✅ | ⬜ | — |
| Health/readiness probes | `GET /healthz`, `GET /readyz` | ✅ | ➖ | — |
| Auth (user/admin tokens) | `X-User-Token`, `X-Admin-Token` headers | ✅ | ✅ | H18.1 / H18.11 |

> Rows with an empty **Task** cell are tracked-but-unscheduled parity gaps. When one becomes
> worth doing on mobile, give it an `H18.x` id in `BACKLOG.md` and fill the cell. Surfaces marked
> ➖ are intentionally desktop-only (e.g. eval/benchmark dashboards) or machine-facing infra
(e.g. the `/healthz`·`/readyz` probes a load balancer / systemd / Docker calls, not a phone) —
note *why* if you add one.

## When you add a NEW hub endpoint

1. Land it for the browser as usual.
2. Add a row here with **mobile = ⬜** (or ➖ with a reason).
3. Decide: does the mobile app need it? If yes → `H18.x` task. If "eventually" → leave the
   Task cell empty (it's now visible in this ledger, not lost).

Keeping this list honest is task **H18.10** — the always-open umbrella in ORIZONT 18.
