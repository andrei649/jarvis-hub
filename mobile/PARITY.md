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
| Dashboard (weather/news) | `GET /dashboard` | ✅ | ✅ | H18.14 |
| Tasks board | `GET /tasks` | ✅ | ✅ | H18.13 |
| Ticker | `GET /ticker` | ✅ | ✅ | H18.14 |
| Skills browser | `GET /skills` | ✅ | ✅ | H18.15 |
| Memory / notes | `GET /memory`, `GET /api/notes` | ✅ | ✅ | H18.16 |
| Knowledge graph | `GET /api/kg/*` | ✅ | ✅ | H18.17 |
| Action approval queue + rollback story | `GET /autonomy/approvals`, `POST /autonomy/tasks/{id}/decision` | ✅ | ✅ | H18.11 / O26-P3.4 / H27.6 |
| Capability registry board | `GET /api/capabilities` | ✅ | ⬜ | H18.22 / H27.8 |
| Channel inbox + governed replies | `GET /api/channels/inbox*`, `POST /api/channels/inbox/{thread_id}/reply` | ✅ | ✅ | H18.12 |
| Chat rooms (multi-agent) | `GET/POST /api/rooms*` | ✅ | ⬜ | — |
| Arena / review / quality | `GET /api/arena/*`, `/api/review/*` | ✅ | ➖ | — |
| Security posture | `GET /api/security/*` | ✅ | ✅ | H18.18 |
| Health/readiness probes | `GET /healthz`, `GET /readyz` | ✅ | ➖ | — |
| First-run command center (0.19) | `GET /api/onboarding/command-center` | ✅ | ✅ | H18.19 |
| Artifacts workspace (Canvas) | `GET /api/canvas`, `POST /api/canvas/post`, `POST /api/canvas/{id}/pin`, `DELETE /api/canvas/{id}` | ✅ | ✅ | H18.20 |
| Media Director (O29, default-off) | `GET /api/media/devices`, `POST /api/media/devices`, `DELETE /api/media/devices/{device_id}`, `GET /api/media/session`, `POST /api/media/present`, `POST /api/media/restore/{device_id}` | ✅ | ✅ | H18.21 |
| House Brain (H30.5, default-off) | `GET /api/house/state`, `POST /api/house/control/{light,climate,security}`, admin-only `/api/house/security/{task_id}/{challenge,confirm}` | ✅ | ✅ | H30.5 |
| Windows server-host desktop actuation (intentionally desktop-only; a phone must not control the server's desktop) | `POST /api/desktop/run` | ✅ | ➖ | — |
| Auth (user/admin tokens) | `X-User-Token`, `X-Admin-Token` headers | ✅ | ✅ | H18.1 / H18.11 |

> **H18.20 ✅ (delivered):** native artifact workspace parity — the Memory tab gains an
> Artifacts view (browse Canvas artifacts with safe typed rendering, remote images behind an
> explicit consent tap, pin/unpin/delete), and Chat gains the explicit save-response control
> (real responding agent, visible 4,000-char truncation on a code-point boundary, never auto).

> **H18.21 ✅ (delivered):** native Media Director parity — a metadata-only Media tab reads the
> owner-curated device registry and live session board, and exposes explicit governed present/restore
> actions with distinct disabled, queued, refused, unverified, and verified outcomes. Device registry
> mutations remain a separate admin-token-gated zone; no remote media is embedded on the phone.

> **H30.5 ✅ (delivered):** native House Brain parity is intentionally read-first: the Home tab
> renders bounded rooms, devices, and pseudonymous presence, then hands governed work to the shared
> Approvals inbox. Reversible and security proposals are visible there, but the security-device
> challenge/confirmation ceremony stays on the owner HUD; the phone has no one-tap unlock/disarm
> or admin confirmation endpoint.

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
