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

Camera parity is read/search parity over the same bounded metadata API. Admin ONVIF onboarding is
intentionally owner-HUD-only; native clients expose no discovery, frame, stream, or private URL.

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
| Memory / notes | read legs only: `GET /memory`, `GET /api/notes` | ✅ | ✅ | H18.16 |
| Knowledge graph | read legs only: `GET /api/kg/entities`, `GET /api/kg/facts/{as-of,history}` | ✅ | ✅ | H18.17 |
| Action approval queue + rollback story | `GET /autonomy/approvals`, `POST /autonomy/tasks/{id}/decision` | ✅ | ✅ | H18.11 / O26-P3.4 / H27.6 |
| Capability registry board | `GET /api/capabilities` | ✅ | ✅ | H18.22 / H27.8 |
| WorldView bridge (World tab: liveness + recon read data) | `GET /api/worldview/status`, `GET /api/worldview/overview` | ✅ | ⬜ | |
| Channel inbox + governed replies | `GET /api/channels/inbox*`, `POST /api/channels/inbox/{thread_id}/reply` | ✅ | ✅ | H18.12 |
| Spoken morning brief (🔊 SPEAK) | `GET /autonomy/brief` + `POST /tts` (native: hub TTS via expo-audio) | ✅ | ✅ | H18.23 |
| Chat rooms (multi-agent) | `GET/POST /api/rooms*` | ✅ | ⬜ | — |
| Arena / review / quality | `GET /api/arena/*`, `/api/review/*`, `GET /api/quality` (open), admin `POST /api/quality/threshold` | ✅ | ➖ | — |
| Security posture | read legs only: `GET /api/security/{governance,kill-switch,loop-breaker}` (open), `GET /api/security/posture` (admin) | ✅ | ✅ | H18.18 |
| Health/readiness probes | `GET /healthz`, `GET /readyz` | ✅ | ➖ | — |
| First-run command center (0.19) | `GET /api/onboarding/command-center` | ✅ | ✅ | H18.19 |
| Artifacts workspace (Canvas) | `GET /api/canvas`, `POST /api/canvas/post`, `POST /api/canvas/{id}/pin`, `DELETE /api/canvas/{id}` | ✅ | ✅ | H18.20 |
| Media Director (O29, default-off) | `GET /api/media/devices`, `POST /api/media/devices`, `DELETE /api/media/devices/{device_id}`, `GET /api/media/session`, `POST /api/media/present`, `POST /api/media/restore/{device_id}` | ✅ | ✅ | H18.21 |
| House Brain (H30.5, default-off) | `GET /api/house/state`, `POST /api/house/control/{light,climate,security}`, admin-only `/api/house/security/{task_id}/{challenge,confirm}` | ✅ | ✅ | H30.5 |
| Camera Intelligence (H31.5, default-off, metadata-only) | `GET /api/cameras/{status,events}`, `POST /api/cameras/search`, admin-only `POST /api/cameras/onvif/discover` | ✅ | ✅ | H31.5 |
| Governed Capability Acquisition (H32.6, default-off) | user `GET /api/acquisition/{status,events}`; admin-only revoke, rollback, ledger export/purge | ✅ | ✅ | H32.6 |
| Ambient Watch (H33.6, default-off, redacted) | user `GET /api/ambient/monitors`; admin-only monitor create/update/delete | ✅ | ✅ | H33.6 |
| Self-Improvement dashboard (admin-only diagnostic aggregation) | admin-only `GET /api/self-improvement/status`, `POST /api/self-improvement/enable` | ✅ | ➖ | — |
| Mission Control (H34.1 — swarm cockpit page + read feed) | `GET /mission-control`, `GET /api/swarm/summary` | ✅ | ➖ | — |
| Live System Map (H34.7 — topology + health page + read feed) | `GET /map`, `GET /api/system-map` | ✅ | ✅ | M6 |
| Owner desk presence (H34.2 — away-notify) | user `GET /api/presence/owner`; admin `POST /api/presence/owner` | ✅ | ➖ | — |
| Governed browser policy / plan preview | `POST /api/browser/check`, `POST /api/browser/plan/preview` | ✅ | ➖ | — |
| Windows server-host desktop Operator | `POST /api/desktop/preview`, `POST /api/desktop/run` | ✅ | ➖ | — |
| Voice orb (particle sphere bound to the voice state machine) | — (client-side, reads the existing `POST /api/voice/stt` + `POST /tts` loop) | ✅ | 🟡 contract ported | H18.24 — the **state→visual contract** (`orbVisual`) is ported to `mobile/src/voice/orbVisual.ts` and proven identical to the browser's against 80 shared vectors (`tests/_fixtures/orb_visual_vectors.json`, asserted by both suites). The **particle renderer** is not ported: RN has no canvas, so it needs a graphics dependency (react-native-svg / Skia) plus on-device validation. Native also cannot yet reach `listening`/`transcribing` — there is no mobile mic-capture pipeline, only TTS playback (H18.5). |
| Briefing wall (neural field + stat board + hold-to-talk) | — (client-side, composed from `/api/agents`, `/tasks`, `/api/trust/status`, `/api/analytics/locality`) | ✅ (responsive: portrait layout under 820px) | 🟡 contract ported | H18.25 — the **state contract** (`wallState`: the word + tone the wall announces) is ported to `mobile/src/voice/wallState.ts` and proven identical to the browser's against **500 shared vectors** (`tests/_fixtures/wall_state_vectors.json`, asserted by both suites). The **neural-field canvas + stat board chrome** is not ported (RN has no canvas → graphics dependency + device validation), and **hold-to-talk cannot exist yet**: there is no mobile mic-capture pipeline at all, only TTS playback (H18.5). |
| Auth (user/admin tokens) | `X-User-Token`, `X-Admin-Token` headers | ✅ | ✅ | H18.1 / H18.11 |
| Global emergency stop (pause new autonomous work; hermes v2026.8.27 port) | user `GET /api/ops/estop`; admin `POST /api/ops/estop/engage`, `POST /api/ops/estop/resume` | ✅ | 🟡 read-only card on Status (engaged/reason/engaged_at); engage/resume intentionally owner-HUD-only | — |
| Ambient Capture (opt-in surfaces, each record deletable) | `GET /api/capture`, `GET /api/capture/status`, `POST /api/capture/clear`, `DELETE /api/capture/{rec_id}` | ✅ | ⬜ | |
| Encrypted personal vault | `GET/POST /api/vault`, `GET/DELETE /api/vault/{vault_id}` | ✅ | ⬜ | |
| Memory search + data-space admin | `GET /api/memory/search`; admin `GET/POST /api/memory/spaces`, `POST /api/memory/spaces/{assign,unassign}`, `DELETE /api/memory/spaces/{name}` | ✅ | ⬜ | |
| Write legs on surfaces mobile already reads (notes, KG, memory decay) | `PUT /api/notes`, `POST /api/notes/rewrite`, `DELETE /api/kg/entities/{name}`, `POST /api/memory/decay/forget` | ✅ | ⬜ | |
| Local docs index | `GET /api/local-docs` (open), `POST /api/local-docs/index` | ✅ | ⬜ | |
| Nightly reflection (status + manual run) | `GET /api/reflection/status`, `POST /api/reflection/run` | ✅ | ⬜ | |
| Security skills browser (ATT&CK tactics → curated techniques, read-only) | `GET /api/security-skills/tactics`, `GET /api/security-skills/techniques` | ✅ | ⬜ | |
| Prompt-injection scan | `POST /api/security/scan-injection` | ✅ | ⬜ | |
| Audit-chain verification (tamper-evidence read) | `GET /api/security/audit/intent`, `GET /api/security/audit/verify` | ✅ | ⬜ | |
| Channel pairing ceremony | admin `GET /api/channels/pairing`, `POST /api/channels/pairing/code`, `POST /api/channels/pairing/decide` | ✅ | ⬜ | |
| Governed social drafts (draft-before-send) | `GET/POST /api/integrations/social` | ✅ | ⬜ | |
| Mic satellites (pair a device as a mic) | `GET /api/satellites`, `POST /api/satellites/register`, `DELETE /api/satellites/{satellite_id}` | ✅ | ⬜ | |
| Oracle sync (conflicts read off the status payload) | `GET /api/oracle/status` (open); admin `POST /api/oracle/sync`, `POST /api/oracle/conflicts/resolve` | ✅ | ⬜ | |
| Packs inventory + verification | `GET /api/packs`, `GET /api/packs/{key}/verify` | ✅ | ⬜ | |
| World signals routing feed | `GET /api/signals/routed`, `GET /api/signals/agent/{agent_id}` | ✅ | ⬜ | |
| Market watchlist (owner-saved rows; no quotes, no trading) | `GET/POST /api/market/watchlist/saved`, `DELETE /api/market/watchlist/saved/{symbol}` | ✅ | ⬜ | |
| Onboarding wizard + funnel steps | `GET /api/onboarding/wizard`, `POST /api/onboarding/funnel` | ✅ | ⬜ | |
| Feedback · NPS (submit + admin summary) | `POST /api/feedback`; admin `GET /api/feedback/summary` | ✅ | ⬜ | |
| Kernel + north-star metric boards | `GET /api/metrics/kernel`, `GET /api/metrics/north-star` (both open) | ✅ | ⬜ | |
| Reasoning traces list | `GET /api/traces` | ✅ | ⬜ | |
| Cognition read + live scoring stream | `GET /api/cognition`, `GET /api/cognition/stream` (SSE) | ✅ | ⬜ | |
| Workflows (list / run / step-generate) | `GET /api/workflows`, `POST /api/workflows/run`, `POST /api/workflows/step/generate`; admin `DELETE /api/workflows/{pipeline_id}` | ✅ | ⬜ | |
| Sandboxed code execution | `GET /sandbox/status` (open), `POST /sandbox/execute` | ✅ | ⬜ | |
| Agent templates (instantiate a config) | `GET /api/agent-templates` (open), `POST /api/agent-templates/instantiate` | ✅ | ⬜ | |
| Publish readiness (creative checklist + package) | `POST /api/creative/publish/checklist`, `POST /api/creative/publish/package` | ✅ | ⬜ | |
| Missions board (long-horizon governed workspaces) | `GET /api/missions`, `POST /api/missions/{mission_id}/{start,pause,resume,complete,cancel}` | ✅ | ⬜ | |
| Today board (daily digest) | `GET /api/dashboard/today` | ✅ | ⬜ | |
| Natural-language schedule parser | `POST /api/schedule/parse` | ✅ | ⬜ | |
| Bench-agent learning + promotion | `GET /learning`; admin `POST /learning/promote`, `POST /api/learning/propose` | ✅ | ⬜ | |
| Heartbeats (per-agent run/start/stop) | `GET /heartbeat/status` (open); admin `POST /heartbeat/{agent_id}/{run,start,stop}` | ✅ | ⬜ | |
| Transcript → tasks ingest | `POST /api/transcripts/ingest` | ✅ | ⬜ | |
| Escalation (ask-tier fan-out) | `GET /api/autonomy/escalation/targets` (open); admin `POST /api/autonomy/escalate` | ✅ | ⬜ | |
| Agent dossier (soul + run history) | `GET /api/agents/{agent_id}/soul`, `GET /api/agents/{agent_id}/history` | ✅ | ⬜ | |
| Local models + cloud auth profiles + VLM status | user `GET /api/vlm/status`; admin `POST /api/llm/{load,unload}`, `GET /api/llm/auth-profiles`, `GET /api/models/info`, `GET /api/models/local`, `POST /api/models/local/switch` | ✅ | ⬜ | |
| System profile (read-only; selected via `JARVIS_SYSTEM_PROFILE`) | `GET /api/system/profiles` | ✅ | ⬜ | |
| Sentence-streamed TTS | `POST /tts/stream` | ✅ | ⬜ | |
| Eval datasets (run / compare / history) | `GET /api/eval/datasets`, `GET /api/eval/datasets/{name}/{runs,compare}` (open), `POST /api/eval/datasets/run` | ✅ | ➖ | — |
| Bench stats | `GET /bench/stats` (open) | ✅ | ➖ | — |

> **H34.1 ➖ (intentional):** Mission Control is a desktop-operator cockpit (large canvas map,
> dev-swarm lock files that only exist on the owner's dev machine). Its steering primitives
> already have native parity through the Approvals tab (H18.11/O26-P3.4) and the read surfaces
> it aggregates are individually available; a phone-sized cockpit is not planned.

> **H34.2 ➖ (intentional):** the `/api/presence/owner` write is a signal *from* the owner's
> desktop host daemon (Windows idle/lock or the Tauri overlay), not a phone control; the phone is
> the away-notify *target* (it receives the escalated cards over WhatsApp/Telegram), so no native
> presence UI is needed. The state is already visible in the Mission Control feed.

> **Eval datasets / bench stats ➖ (intentional):** these inherit the decision this file already
> records — the foot of the matrix marks eval/benchmark dashboards as intentionally desktop-only,
> and the `Arena / review / quality` row is already ➖ on exactly that basis. They are developer
> regression tooling read while changing the hub, not owner surfaces.

> **On the ⬜ rows added above:** every one of them is *not ported* — no native screen, no client
> call, no partial. Several would be defensible ➖ candidates (sandboxed execution and the local-model
> lifecycle are hub-host capabilities; heartbeats, channel pairing and escalation are admin
> ceremonies), but no such decision exists in the repo today, so recording one here would be the
> aspiration-as-fact this ledger exists to prevent. They stay ⬜ until the owner triages them.

> **H18.20 ✅ (delivered):** native artifact workspace parity — the Memory tab gains an
> Artifacts view (browse Canvas artifacts with safe typed rendering, remote images behind an
> explicit consent tap, pin/unpin/delete), and Chat gains the explicit save-response control
> (real responding agent, visible 4,000-char truncation on a code-point boundary, never auto).

> **H18.21 ✅ (delivered):** native Media Director parity — a metadata-only Media tab reads the
> owner-curated device registry and live session board, and exposes explicit governed present/restore
> actions with distinct disabled, queued, refused, unverified, and verified outcomes. Device registry
> mutations remain a separate admin-token-gated zone; no remote media is embedded on the phone.

> **H18.23 ✅ (delivered):** native spoken morning brief — the Status tab gains a "Morning
> brief" card reading the admin-guarded `GET /autonomy/brief` text, with a 🔊 Speak/Stop control
> that plays it through the existing hub-TTS + expo-audio path (`src/audio/tts.ts`). Honest
> states: no admin token → a pointer to Settings; hub TTS unavailable → a visible error, never
> fake playback.

> **H18.22 ✅ (delivered):** native capability registry parity, folded into the existing Status
> tab (not a new top-level tab — the tab bar was already at 13 items) as a "Capabilities" card
> alongside Trust: SEAM/WIRED/VERIFIED/GA counts off the same `GET /api/capabilities` the HUD's
> `ReadinessPanel` reads, plus the honest "harness pending — wired, not yet proven" note when
> nothing has been VERIFIED yet. Read-only, matching the mobile-wide read-first pattern.

> **H30.5 ✅ (delivered):** native House Brain parity is intentionally read-first: the Home tab
> renders bounded rooms, devices, and pseudonymous presence, then hands governed work to the shared
> Approvals inbox. Reversible and security proposals are visible there, but the security-device
> challenge/confirmation ceremony stays on the owner HUD; the phone has no one-tap unlock/disarm
> or admin confirmation endpoint.

> **H32.6 ✅ (delivered):** native acquisition parity is intentionally read-only. The Acquire tab
> shows lifecycle counts, reuse rate, signed sandbox-only package metadata, and bounded audit event
> metadata over the shared user endpoints. Permanent approval, revoke/rollback, and ledger
> export/purge remain in the owner HUD's separately authenticated admin zone.

> **H33.6 ✅ (delivered):** native Ambient Watch parity is intentionally read-only. The Watch tab
> shows bounded monitor/source health, the last redacted policy decision, per-rung counts, and the
> single global attention budget. Predicate values, subjects, event fingerprints/content,
> recipients, and admin monitor mutations remain on the owner hub.

> **H28 Operator boundary:** governed browser checks and plan previews are owner/server-browser
> dry runs, not native execution. A native `toolrpc.desktop_run` approval card hides the desktop
> payload and has no **Approve** control; Reject and Defer remain, and approval continues in the
> Owner HUD. This is a mobile UI boundary only and does not change the generic task API or server
> authorization.

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
