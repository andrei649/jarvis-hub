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

SEC-B6 local source candidate (2026-11-03): twelve owner-content reads now require
user credentials: `GET /api/oracle/status`, `GET /agents`, the three
`GET /api/eval/datasets` list/runs/compare routes, `GET /learning/stats`,
`GET /api/local-docs`, `GET /skills/imported`, `GET /api/arena/leaderboard`,
`GET /api/metrics/kernel`, `GET /api/metrics/capabilities`, and
`GET /sandbox/status`. Existing user clients send `X-User-Token`; an authorized
admin credential also satisfies a user read. The v1 HUD's stored-token fetch
helper resolves the actual URL origin and clones request options before adding
the token, so protocol-relative external URLs and reused options cannot carry
its injected token. The standalone admin page uses its existing admin-token
helper for Agents and Oracle status/conflicts GETs.

The successful public `GET /api/security/kill-switch` returns exactly `global`,
`any_halted`, and `halted_count`; full halted scopes/reasons remain on admin
`GET /api/security/kill-switch/details`. Browser and mobile read consumers
distinguish global from scoped halts and leave missing, failed, or contradictory
aggregates unknown rather than reporting operational. The browser global
control still changes only global scope and cannot release individual scoped
halts. Mobile has a read-only Status row, with no native halt control. Focused
local tests and typechecks cover these clients; physical-device, networked-Hub,
and served-browser acceptance are not claimed here.

H456 local candidate (2026-10-10): CLI/web Jobs author per-job reasoning effort
and expanded installed tool groups; scheduled dispatch applies operator and
platform restrictions. Native mobile authoring for these choices remains open.
No native-device validation is claimed. See [job policy](../docs/automations-operations.md#tool-limits-and-reasoning).

H453/H454 local candidate (2026-10-10): scheduled scripts distinguish complete
safe stdout from bounded summaries; CLI/admin API author cross-job `context_from`
alongside own-output continuity. Native mobile source selection, output inspection
and dedicated continuity controls remain open. No mobile adapter or native-device
acceptance is added. See [job context](../docs/automations-operations.md).

H015 local candidate (2026-10-10): shared admin APIs add incident acknowledgement,
named job notes, explicit continuity and history after job removal. Native mobile
administration for these operations remains open; this batch supplies no new
mobile adapter or native-device acceptance. The existing web Jobs diagnostic and
legacy notes controls remain. H049 named log reading is host CLI administration.
See [scheduled-job operations](../docs/automations-operations.md).

H002 local candidate (2026-10-10): JSON chat replies and SSE end events carry an
additive request-owned generation-usage snapshot. Native clients retain their
existing chat rendering; no native spend panel is implemented in this batch.
Atomic `--usage-file` export is intentionally a host CLI capability. It counts
accepted generation attempts and preserves unknown values instead of guessing
costs. See [CLI receipt semantics](../docs/cli-chat-receipts.md). This is not a
native-device acceptance claim.

H441 local candidate (2026-10-10): native clients inherit owner-only access to
imported/derived sessions and suppression from guest session/checklist lists.
The existing exact-ID resume and recap contract is retained. This batch adds
CLI/API selectors and foreign imports, with no browser/native import picker.
Reading Claude Code/Codex source files is intentionally CLI-host administration;
there is no native-device acceptance claim. See
[resume/import guide](../docs/foreign-session-resume.md). H398 completeness/risk
handling and H667 temporary-directory resolution are shared runtime behavior,
with no new native chat field or control.

H329 local update (2026-10-10): the browser Skill Switches panel and terminal
picker show re-enable requests as pending until the approved worker applies
them. Disabled skills stay installed. Shared server enforcement applies to all
channels; corrupt/missing switch state refuses nonessential skills. Native
mobile currently has the read-only skills browser, with no switch editor or
interactive picker; these controls remain desktop/host administration. Existing
approval surfaces consume the same bounded task. H299/H397 stall guidance and
opt-in stops are shared runtime behavior, with no new native screen.

H413/H689 local update (2026-10-10): existing session lists receive the same
instant and background-upgraded titles; automatic naming now uses the dedicated
small local model, and keeps the instant title when it is unavailable. Profiles
share installation identity while retaining separate credentials and stores.
Existing owner node-registration and sender-link endpoints refuse missing
identity with HTTP 503; identity reconciliation/re-pairing remains host
administration, with no new native management screen or device acceptance claim.
See [migration guide](../docs/install-identity.md) and
[batch verification](../docs/plans/2026-10-10-hermes-closure-02.md).

H256 local update (2026-10-10): existing owner consent endpoints now refuse a
damaged settings store before audit or grant/revoke. Their existing error path
is retained; this adds no mobile consent or configuration-repair screen.

Camera parity is read/search parity over the same bounded metadata API. Admin ONVIF onboarding is
intentionally owner-HUD-only; native clients expose no discovery, frame, stream, or private URL.

H063 gateway reset/index/stall policies are host/channel behavior, with no new
mobile endpoint or lifecycle controls. Mobile HTTP chat keeps its existing
lifecycle. Native configuration and device acceptance are not claimed by the
gateway implementation.

Media integrity (local backend candidate, 2026-10-09): newly cloud-finalized, ComfyUI and local OpenAI PNG `md-*` catalog rows bind their producer digest for shared delivery and export. Both clients inherit a refusal for mismatched bytes on those catalog URLs. Existing blob headers and gallery controls are unchanged; verified/unbound status is export metadata only. New ComfyUI, local OpenAI and cloud standalone generated-image URLs and edit references also verify an expected sidecar digest through the shared server reader; mismatches and invalid bindings use the existing opaque refusal. These built-in producers share the reserved-ID publisher, while cloud task recovery keeps its independent completion hash. Missing sidecars retain legacy availability without digest verification. Legacy/other unsupplied catalog rows retain their own limits. Native wire shapes and UI stay unchanged (H477 partial).

Tool profile permissions (local backend candidate, 2026-10-09): both clients inherit a live profile check before each new tool dispatch in the enabled production agent loop. A tool withdrawn since the model saw it is refused before preflight or approval intake. Existing error shapes and client controls are unchanged; already-running tools and queued approvals are outside this check (H672 partial).

Tool-loop exit diagnostics (H396 local backend candidate, 2026-10-09): the runtime
retains a typed result and a bounded diagnostic for one normal returned tool-loop
invocation. Existing Agent callers still receive the same text. No new field is
sent to browser/native chat; whole-turn attribution and client explanations remain
open and must extend the shared H686 outcome after their semantics are defined.
See [runtime evidence](../docs/project-tool-loop-exit-result-20261009.md).
Returned approved file execution now also carries an additive per-attempt mutation
receipt in its existing task result. It does not add a browser/native chat field
or mutation footer; missing/cancelled results and cross-task attribution remain
open. See [receipt evidence](../docs/project-file-mutation-receipts-20261009.md).

Document extraction limit (H444/H576 local backend candidate, 2026-10-09):
parser-backed file_read refuses observed PDF/DOCX input above 50,000,000 bytes
before parser discovery. Raw byte paging remains available; this is an observed
input-size check, not a parser memory bound. Existing chat/tool result handling
carries the named refusal; no new native presentation is required. See
[document input evidence](../docs/project-document-input-limit-20261009.md).

PDF text coverage (H444/H576 local backend candidate, 2026-10-09): significant
no-text page ranges now appear as bounded metadata in the existing file_read
result, with preceding source quotes and explicit omission counts. Extracted
content and byte pagination are unchanged. Both clients inherit the model-side
warning; there is no new HTTP/SSE field or dedicated native PDF warning card.
See [coverage evidence](../docs/project-pdf-text-coverage-20261009.md).

Session ID validation (local backend candidate, 2026-10-09): both clients inherit
strict full-string session validation on the existing shared server boundaries.
A terminal newline is refused before session or memory work; valid IDs retain
their exact value. Native JavaScript validation already rejects this input.
No wire shape or UI change; device/live-Hub acceptance remains open. See
[backend evidence](../docs/project-session-id-validation-20261009.md).

## Combined local mobile candidate — 2026-10-09

The local integration branch combines session continuity, command discovery, connected memory,
advisory approval opinions, generated images, selected-image review/history, voice orb,
push-to-talk and briefing sources. Full mobile284/native137, TypeScript and Android/iOS
exports pass. Photo selection and dictation retain separate explicit controls; switching
modes revokes stale capture/review callbacks. Physical-device and live-Hub acceptance
remain open, so the partial rows below do not become shipped. Details and source commits:
[combined evidence](docs/mobile-integration-20261009.md).

## Parity matrix

| Surface | API (agents/web.py) | Browser | Mobile | Task |
|---------|---------------------|:-------:|:------:|------|
| Managed Hermes runtime and exact action approvals | Admin `/api/hermes/{status,catalog,start,stop,rpc,ws,approvals}` and approval decision API | ✅ private runtime, sessions, methods, events, approve/deny controls | ➖ intentionally owner desktop administration; no native acceptance claimed | PR #1233 |
| Signed model-provider installation, credentials and selection | Admin package lifecycle plus default-off owner GET/PUT/DELETE `/api/admin/llm/provider-credentials` and `/api/admin/llm/provider-selection`; exact signed binding, revision and credential generation; metadata-only readback | ⬜ owner APIs and guarded six-dialect sends; HUD review, key entry, risk acknowledgement and selection controls remain open | ➖ owner desktop administration; no native install/key/selection controls or device acceptance | H361 partial; local synthetic owner/Kernel/Vault/TLS tests cover source behavior; live provider, Docker, SDK and platform breadth remain open |
| Chat (streaming) | `POST /chat/stream`, `POST /chat` | ✅ | ✅ | H18.1 |
| Current-turn duration (H686 first slice) | optional `outcome.latency_ms` on `/chat` and SSE end; owner `display.status_bar_fields` | ✅ local cockpit and focus-chat readout; normal returned turns only, ephemeral | 🟡 local current-turn readout from validated explicit SSE end; clears on work/context changes and never persists; physical-device/live-Hub acceptance open | H18.33 / H686; [evidence](docs/h1833-turn-duration.md) |

| Selected Ollama image turns and active history | owner GET active-images and POST selected-prepare/selected-chat under /api/vlm/composer | ✅ all active HUD composers, exact model/session review and stale-response fences | 🟡 local candidate: frozen picker snapshots, exact session/agent/model review, explicit send, active-image choices and durable unknown-delivery handling; device/live-Hub acceptance open | H18.31 / H277 |

| Owner quick commands | existing chat slash dispatch and Admin commands.quick_commands JSON | ✅ existing Admin configuration, /help and approval tasks | ✅ typed aliases/fixed commands use the same governed chat path; native live catalog implemented locally, device acceptance open | H078 / H18.26 |

| Session command ID transitions (/new, /reset, /undo) | POST /chat and /chat/stream return session_id; existing POST /sessions/resume | ✅ concrete topic state, old-topic reopening and desktop sync | 🟡 implemented: exact selected ID, scoped restart persistence, governed New/reset and undo refresh; unit/mounted-host verified, device acceptance open | H18.30 |

| Code execution project context and persistence | existing admin settings and sandbox status/reset | ✅ existing Admin settings and sandbox surface | ➖ operator configuration stays on the owner HUD; chat tools use the same governed backend | H595/H660, remote transports remain partial |
| Chat-command catalog (live registry, filtered by chat principal) | `GET /api/commands` | ✅ quickbar menu | 🟡 native Chat modal lists live command, usage, description and owner tier; loading, empty, error and unavailable states, retry, and composer insertion are host-tested. Device/live-Hub acceptance open; Send stays on governed chat path | H18.26 |
| Chat/session protocol discovery | `GET /v1/capabilities` | ➖ machine-readable client contract; no HUD control | ➖ available to authenticated clients; current native transport remains fixed to its tested contract, runtime negotiation is not implemented | H477 partial |
| Owner checkpoint operations (H011, partial) | Existing `POST /chat`, `POST /chat/stream`; no new route | Owner inventory, diff, selected/force restore and index maintenance through typed commands and host CLI; signed human task + kernel execution; successful restore rewinds only the current last-user exchange | ⬜ dedicated checkpoint UI and native acceptance; no native implementation claimed | H011 / H18.26; size/retention controls and complete checkpoint-owned payload cleanup remain open; shared blobs retained |
| Chat history persistence | — (client-side) | ✅ | ✅ | H18.2 |
| Agent selection | user `GET /api/agents`, `agent` param | ✅ | ✅ | H18.3 |
| Owner browser sign-in (H509, partial) | `GET /api/auth/session`, `POST /api/auth/login`, `/logout`, `/logout-all` (admin) | ✅ sign-in screen on a networked origin, CSRF on cookie writes, sign-out / sign-out everywhere | ➖ intentionally browser-only: the native app keeps its header token (no cookie jar to protect) | G13 |
| Runtime Inspector (H227) | Existing admin inspector route | ✅ model/route resolution, unresolved/legacy/withheld states and fixed empty-turn limits | ⬜ dedicated native inspector; intentional owner administration gap | H18.26 / H227 |
| Durable Kanban and approved workers (H075/H581, partial) | Owner `/kanban` and `nerva kanban`, scoped admin `/api/kanban` board/task/file APIs and authenticated board event WebSocket; signed dispatch queue, bounded parallel workers, cancellation and separately approved URL attachments; flags default off | 🟡 ProjectsMode board and task drawer: board/task CRUD, bulk changes, comments, local attachment upload/download, project/profile/orchestration reads, explicit dispatch request, event refresh with reconnect and poll; existing approval queue. Advanced profile/orchestration/log/model/transfer and worker/recovery actions remain open; file-mutation callback prerequisite is not wired | ⬜ native board/worker controls and attachments | H18.34 / H075 / H581; no full Hermes parity or native acceptance claimed |
| Markdown rendering | — (client-side) | ✅ | ✅ | H18.4 |
| Status / telemetry | `GET /status` | ✅ | ✅; local refresh-order fix protects model/Trust/brief data and loading/error state from older responses | H18.1; [refresh evidence](docs/native-status-refresh-order.md) |
| Sessions (resume) | `GET /sessions`, `POST /sessions/resume` | ✅ | ✅ | H18.5 |
| Voice / TTS | `POST /tts` | ✅ | ✅ | H18.5 |
| Speech-only verifier advisory filtering (H526 checkpoint) | Shared hub TTS normalizer; footer-only replies return 204 | Whole replies and live deltas filter the exact structured advisory; visible text stays intact | Existing native `/tts` path inherits hub normalization; no separate client parser or device-audio claim | H526 final whole-contract acceptance pending |
| Approved speech command configuration | `GET/POST /api/admin/voice/commands` | ✅ Settings → Voice → Command providers; independent named TTS/STT, signed registration, human approval, revisioned clear and STT selection | ⬜ native provider configuration; hub TTS playback remains available | H517 / H613; vendor/plugin breadth remains open |
| Stream timeout / reconnect | — (client-side) | ✅ | ✅ | H18.6 |
| Dashboard (weather/news) | `GET /dashboard` | ✅ | ✅ | H18.14 |
| Tasks board | `GET /tasks` | ✅ | ✅ | H18.13 |
| Ticker | `GET /ticker` | ✅ | ✅ | H18.14 |
| Skills browser | `GET /skills` | ✅ | ✅ | H18.15 |
| Conditional model-facing skill offers (H328) | Shared prompt catalog and `skills_list` gates now recognize native Kanban and supported toolset members | ✅ shared runtime | ✅ same server-side turn policy; no new native control | H328 |
| Resource-pressure warnings (H161) | `GET /api/system/pressure`, `POST /api/system/pressure/dismiss`; unreadable volumes retain their warning until confirmed recovery | ✅ existing ranked banner | ⬜ native banner/dismissal reader remains open | H161 |
| App-timezone schedules (H450) | Existing schedule preview and jobs APIs use the same active application zone; saved zone changes apply to running jobs after restart | ✅ existing Jobs preview/create/edit | ⬜ native job administration remains open; shared backend behavior applies to all callers | H450 |
| Memory / notes | read legs only: `GET /memory`, `GET /api/notes` | ✅ | ✅ | H18.16 |
| Knowledge graph | read legs only: `GET /api/kg/entities`, `GET /api/kg/entities/{name}`, `GET /api/kg/facts/{as-of,history}` | ✅ | ✅ existing native entity list/detail and relation rows | H18.17 |
| Memory neighborhood navigation | user/admin-superset `GET /api/kg/entities`, `GET /api/kg/entities/{name}`, plus KG fact reads | ✅ live search, selectable connections, bounded reads; samples only in explicit Demo | 🟡 local Graph code: connected navigation outside first 50, cancellable ten-second reads, post-body one-MiB verification, 100-row caps, stale-read guards and explicit unavailable states; device/live-Hub acceptance open | DW-1 / H18.28 |
| Action approval queue + rollback story | `GET /autonomy/approvals`, `POST /autonomy/tasks/{id}/decision` | ✅ | ✅ | H18.11 / O26-P3.4 / H27.6 |
| Reusable terminal consent (H487) | Optional public `consent_offer` on `GET /autonomy/tasks`; admin `POST /autonomy/tasks/{id}/consent` with exact revision | Decision Inbox offers session/always/deny for current reviewed terminal categories; ordinary once controls remain | ⬜ native reusable choices and device acceptance; ordinary native decisions remain available | H487 remains partial: Telegram, other producers and broader interactive parity remain open |
| Task mediation evidence status | admin `GET /autonomy/mediation` | ✅ local Autonomy Control candidate: effective mode and verified aggregate counts; invalid/unavailable evidence hides counts | 🟡 local Status card after Trust: strict counters, mode/evidence separation, refresh and connection/read-order fences; device/live-hub acceptance open | [H18.32 evidence](docs/h1832-task-mediation-status.md) / DRA-59 |
| Advisory approval model opinions (H277) | Optional `judge` / `judge_pending` on blocked tasks; `GET /api/llm/roles` configuration | ✅ Decision Inbox opinion, bounded polling and model roles viewer | 🟡 local candidate: advisory opinion and read-only roles view; pending says pull to refresh; no automatic polling; #1233 integration and device/live acceptance open | H18.29 / H277 |
| Opt-in terminal guardian verdicts (H277) | Same blocked-task projection: `judge.advisory=false`, strict `decision`; pending `judge_mode=smart` | ✅ DENY/ESCALATE, guardian identity and one-task owner override; smart approvals leave the inbox | ⬜ distinct guardian verdict/pending labels; existing owner decisions remain usable | H18.29 / H277 |
| Guardian denial feedback and observers (H485) | Bounded next authenticated owner-turn prompt observation; consented server extension events around native guardian request/committed decision | Server chat flow warns after repeated DENYs; observer subscriptions use extension declarations, no dedicated HUD editor | Native settings/labels, observer management and device acceptance remain open; no new mobile client implementation | H485 |
| Capability registry board | user `GET /api/capabilities`; user `GET /api/metrics/capabilities` has no dedicated client caller | ✅ registry board over `/api/capabilities` | ✅ registry board over `/api/capabilities`; no metrics-route caller | H18.22 / H27.8 |
| WorldView bridge (World tab: liveness + recon read data) | `GET /api/worldview/status`, `GET /api/worldview/overview` | ✅ | ⬜ | |
| Channel inbox + governed replies | `GET /api/channels/inbox*`, `POST /api/channels/inbox/{thread_id}/reply` | ✅ | ✅ | H18.12 |
| Slack/Discord inbox replies | Same inbox/reply API; exact room/thread target, existing approval queue | ✅ live inbox composer | ✅ existing Comms screen and client; requires host adapters; Slack automatic ingress uses optional Socket Mode ([setup](../docs/SLACK_SETUP.md)) | HA-4i-comms / 4i-socket |
| Native Slack slash commands (H057, local 2026-11-12) | Host Socket Mode ingress and `/nerva` fallback; existing command access/inbox/approval flow | Existing inbox and approval surfaces; no new screen | Host/Slack-specific; no new mobile route or screen | Live Slack workspace acceptance unverified |
| Owner maintenance chat (H084, local 2026-11-12) | Shared `/reload-skills` and `/debug` registry | Existing chat; `/debug` returns local host path | No device acceptance; no report-download screen | Private report creation currently unavailable on Windows |
| Native Discord commands (H057) | Host SDK command tree; same Gateway and governed replies | Existing inbox/approval surfaces | Discord host integration; no new mobile screen | Live Discord acceptance unverified |
| Skill slash loads and `/commands` discovery (H079) | Existing chat and command registry; owner skill loads share guarded turn context | V24 command catalog adds bounded owner-only quick/skill/bundle entries and partial/truncated notices | V24 command modal accepts legacy catalogs and new shortcut rows, inserts the exact command into the composer, clears on credential/scope changes; device acceptance unrun | Plugin commands and Telegram/Discord skill menus implemented locally; live provider/device acceptance unrun |
| Inbound media byte limit (H070) | Existing settings API, `channels.max_inbound_media_bytes`; live Telegram/email enforcement | Existing generic admin settings | Existing settings API; no dedicated media-limit control added or device-tested | Default 8 MiB, ceiling 20 MiB |
| Channel opening budget (H083, local V45) | Existing admin settings API, `system.channel_connect_timeout_seconds`; Telegram identity, Discord gateway opening, ntfy opening, IMAP connect/login and Slack initial auth/Socket Mode opening, applied at next hub startup | Existing generic admin settings editor; bounded numeric value | No native operator editor added or device-tested; configuration remains on the owner HUD | Local opening deadline tests cover all five transports; worker/SDK cleanup can outlive the budget and live Discord recovery remains unverified |
| Web outbound text gate (H069) | Main HTTP/SSE, clarify/poll labels and selected titles sanitized; original choice indices preserved | Empty SSE final replaces draft; tested App events | Server protection applies; mobile empty-final handling/device acceptance not newly verified | Other provider protocols and attachment bytes remain open |
| Shell reply command (`nerva send --list/--to`) | Same inbox/reply API above; queued task is not a delivery receipt | ✅ existing inbox | ✅ existing inbox; CLI itself is host-only | HA-4i |
| Spoken morning brief (🔊 SPEAK) | `GET /autonomy/brief` + `POST /tts` (native: hub TTS via expo-audio) | ✅ | ✅ | H18.23 |
| Chat rooms (multi-agent) | `GET/POST /api/rooms*` | ✅ | ⬜ | — |
| Arena / review / quality | user `GET /api/arena/leaderboard`; other `/api/arena/*` and `/api/review/*` retain their own guards; `GET /api/quality` (open), admin `POST /api/quality/threshold` | ✅ | ➖ | — |
| Security posture | public `GET /api/security/kill-switch` exact `{global, any_halted, halted_count}`; admin `GET /api/security/kill-switch/details` full `{global, halted}`; `GET /api/security/{governance,loop-breaker}` (open), `GET /api/security/posture` (admin) | ✅ aggregate warnings in Trust/Console; legacy admin details | ✅ read-only aggregate Status, scoped/global/unknown distinct; no device acceptance claimed | H18.18 |
| Health/readiness probes | `GET /healthz`, `GET /readyz` | ✅ | ➖ | — |
| First-run command center (0.19) | `GET /api/onboarding/command-center` | ✅ | ✅ | H18.19 |
| Artifacts workspace (Canvas) | `GET /api/canvas`, `POST /api/canvas/post`, `POST /api/canvas/{id}/pin`, `DELETE /api/canvas/{id}` | ✅ | ✅ | H18.20 |
| Media Director (O29, default-off) | `GET /api/media/devices`, `POST /api/media/devices`, `DELETE /api/media/devices/{device_id}`, `GET /api/media/session`, `POST /api/media/present`, `POST /api/media/restore/{device_id}` | ✅ | ✅ | H18.21 |
| Local image generation (ComfyUI and configured images API, default-off) | `GET /api/media`, `POST /api/media/generate`, admin-only `GET /api/media/generation-tasks/{task_id}`, user-guarded `GET /api/media/generated/{artifact_id}` | ✅ Console → Build → Images: backend/model selection with per-backend edit/upscale capabilities, exact prompt, existing Inbox approval, one-task state, authenticated PNG preview/download and opt-in gallery; resume by task ID. Typed local API/ComfyUI history errors and proven cloud response failures stay distinct from uncertain outcomes; live service proof pending | 🟡 local candidate: exact-prompt local proposals, scoped task restoration, manual refresh, authenticated PNG preview and saved copy; shared reader distinguishes typed local API/ComfyUI history errors and narrowly proven cloud response failures, with no preview/resubmission; legacy/incomplete/ambiguous results stay uncertain and real-device/live-generator acceptance remains open | H18.27 / HA-4i-image / H517 |
| House Brain (H30.5, default-off) | `GET /api/house/state`, `POST /api/house/control/{light,climate,security}`, admin-only `/api/house/security/{task_id}/{challenge,confirm}` | ✅ | ✅ | H30.5 |
| Camera Intelligence (H31.5, default-off, metadata-only) | `GET /api/cameras/{status,events}`, `POST /api/cameras/search`, admin-only `POST /api/cameras/onvif/discover` | ✅ | ✅ | H31.5 |
| Governed Capability Acquisition (H32.6, default-off) | user `GET /api/acquisition/{status,events}`; admin-only revoke, rollback, ledger export/purge | ✅ | ✅ | H32.6 |
| Declared and active extension inspection (local V44/V46/V47) | user `GET /api/plugins/extensions`; offline host `nerva extensions doctor`, online `extensions list` | ✅ Build → Extensions read-only snapshot | ✅ Status → Extensions opt-in snapshot; user-token GET, connection/close fencing; live-device acceptance unverified | HA-4i-S1 |
| Permission ledger (consent grants + revoke) | `GET /api/permissions`, `POST /api/permissions/{grant_id}/revoke` | ✅ | ⬜ | |
| Ambient Watch (H33.6, default-off, redacted) | user `GET /api/ambient/monitors`; admin-only monitor create/update/delete | ✅ | ✅ | H33.6 |
| Self-Improvement dashboard (admin-only diagnostic aggregation) | admin-only `GET /api/self-improvement/status`, `POST /api/self-improvement/enable` | ✅ | ➖ | — |
| Mission Control (H34.1 — swarm cockpit page + read feed) | `GET /mission-control`, `GET /api/swarm/summary` | ✅ | ➖ | — |
| Live System Map (H34.7 — topology + health page + read feed) | `GET /map`, `GET /api/system-map` | ✅ | ✅ | M6 |
| Owner desk presence (H34.2 — away-notify) | user `GET /api/presence/owner`; admin `POST /api/presence/owner` | ✅ | ➖ | — |
| Governed browser policy / plan preview | `POST /api/browser/check`, `POST /api/browser/plan/preview` | ✅ | ➖ | — |
| Windows server-host desktop Operator | `POST /api/desktop/preview`, `POST /api/desktop/run` | ✅ | ➖ | — |
| Host capability probe (what this host can honestly offer the operator, and why not) | `GET /api/host/probe` | ⬜ route shipped, no HUD panel yet | ➖ hub-host capability (the probe describes the hub box, not a phone) | — |
| Voice orb (particle sphere bound to the voice state machine) | — (client-side, native `POST /tts` playback and `POST /api/voice/stt` dictation) | ✅ | 🟡 local renderer + voice candidate | H18.24 — shared 80-vector visual contract retained; native SVG, real TTS events and explicit dictation now drive Chat. Listening uses confirmed native recording and optional measured dBFS; preparation/stopping are distinct from measured activity. STT appends to the draft only. Scope/background/permission cancellation and serialized recorder cleanup implemented; physical-device/live STT acceptance remains open. See [orb](docs/h1824-native-orb.md) and [dictation](docs/native-push-to-talk.md) evidence. |
| Briefing wall (neural field + stat board + hold-to-talk) | — (client-side; health, agents, running tasks, trust, locality, approvals, dashboard, status, voice capabilities, heartbeat status reads) | ✅ (responsive: portrait layout under 820px) | 🟡 local wall candidates | H18.25 — Chat opens a bounded native SVG tier field, source-backed cards/chips/rail and explicit dictation-to-draft. Ten bounded sources include returned decisions, calendar sample, model/voice reports and heartbeat schedules; private task/event/provider details are discarded. Transcript hidden per visit; refresh/background/scope clear evidence. Empty calendar and unknown model residency stay unknown; task/approval counts are bounded feeds and locality excludes unknown routes. Shared 500-vector state contract retained. Device/live-Hub acceptance remains open. See [wall evidence](docs/h1825-briefing-wall.md) and [additional sources](docs/h1825-briefing-sources.md). |
| Auth (user/admin tokens) | `X-User-Token`, `X-Admin-Token` headers | ✅ | ✅ | H18.1 / H18.11 |
| Global emergency stop (pause new autonomous work; hermes v2026.8.27 port) | user `GET /api/ops/estop`; admin `POST /api/ops/estop/engage`, `POST /api/ops/estop/resume` | ✅ | 🟡 read-only card on Status (engaged/reason/engaged_at); engage/resume intentionally owner-HUD-only | — |
| Ambient Capture (opt-in surfaces, each record deletable) | `GET /api/capture`, `GET /api/capture/status`, **`GET /api/capture/export`** (new), `POST /api/capture/clear`, `DELETE /api/capture/{rec_id}` | ✅ | ✅ | T-0.26 — native **Capture** tab (`mobile/src/screens/CaptureScreen.tsx`): inspect every record, forget one, clear the inbox, and take the portable export off the box. **Arming stays off the phone by decision, not by permission** — `POST /api/capture/surfaces` and `POST /api/capture/ingest` are user-guarded and reachable, and are deliberately absent: enabling a surface arms an ambient recorder on a machine you are not sitting at, so a lost or borrowed handset must not be a way to start recording someone else's desk. Deleting is safe in the direction that matters (worst case: losing a record you wanted, never gaining one nobody consented to). The master switch and the per-surface opt-ins are carried through **unflattened** — a surface on with capture off records nothing, and the screen says so in its own words rather than rendering it as "capturing" — and a failed fetch reads as *unknown*, never as "off", which would be the most reassuring possible lie here. |
| Encrypted personal vault | `GET/POST /api/vault`, `GET/DELETE /api/vault/{vault_id}` | ✅ | ⬜ | |
| Memory search + data-space admin | `GET /api/memory/search`; admin `GET/POST /api/memory/spaces`, `POST /api/memory/spaces/{assign,unassign}`, `DELETE /api/memory/spaces/{name}` | ✅ | ⬜ | |
| Memory consolidation (preview existing → plan → dry-run/apply) | `GET /api/memory/consolidate/preview`, `POST /api/memory/consolidate`, `POST /api/memory/consolidate/apply` | ✅ | ⬜ | |
| Curated core memory status, reset and owner switch (H422) | user `GET /api/memory` (ring sizes against the 2200/1375 budgets); admin `POST /api/memory/reset` (typed `RESET`) and `POST /api/memory/switch` | ✅ Long-Term Memory panel: sizes against budgets and typed reset; `nerva memory status\|reset\|off\|on` | ⬜ no native sizes, reset or switch; the shared server applies the switch and budgets to native chat turns | H18.35 / H422 |
| Memory writes the post-turn review holds for the owner, and the write-approval gate (H443) | admin `GET /api/memory/proposals`, `POST /api/memory/proposals/{id}/decide`, `POST /api/memory/approval`; the card also decides through `POST /api/actions/{id}/decide` | ✅ Long-Term Memory panel: held writes with each fact, its ring and why it waits; approve / reject with the hub's own outcome; the gate switch | ⬜ no native list of held writes and no gate switch; the shared server applies the gate to native chat turns | H443 |
| Named skill bundles (H026) | user `GET /api/skills/bundles`, `GET /api/skills/bundles/{name}`; admin `POST /api/skills/bundles`, `POST /api/skills/bundles/reload`, `DELETE /api/skills/bundles/{name}`; on/off through `POST /api/skills/switch` with `bundle`; `/<bundle>` and `/bundle <name>` in chat | ✅ Skill Switches panel lists bundles and switches them as one unit; owner `/<bundle>` loads members into a turn | 🟡 owner `/<bundle>` works through the shared `/chat` path; no native bundle list, editor or switch | H18.35 / H026 |
| Skill provenance, usage counters and the owner's pin (H349) | user `GET /skills` (`usage`: counters, `origin`, `source`, `pinned`, `pinnable`); admin `POST /api/skills/pin` | ✅ Skill Switches panel shows where each skill came from, its counters and its pin, and pins or unpins; `nerva skills pin\|unpin` and `nerva skills list` | ⬜ no native skill list or pin | H18.35 / H349 |
| Goal entry points (H462) | admin `POST /api/company/goals`; `/goal` (stop, pause, resume, status) and `/subgoal` (remove, clear) in chat | ✅ Company room PROPOSE A GOAL form and add-criterion control | 🟡 owner `/goal` and `/subgoal` work through the shared `/chat` path; no native goal form | H18.35 / H462 |
| Service status and slot holders (H019) | `GET /status` `service` and `slots` blocks; user `GET /api/status/slots` (holders) | ➖ read by `nerva status`; the HUD does not render them | ➖ host CLI administration; no native surface planned | H019 |
| Per-turn memory recall line (H430) | `outcome.recall` on `/chat` and the SSE end event (`nerva.recall-status.v1` per provider, last prefetch only); channel reply footers | ✅ HUD turn outcome shows the recall line; Telegram and other channel replies carry it as a text footer, never in a spoken clip | ⬜ native chat does not render the recall line yet; the server already sends it in the shared payload | H18.36 / H430 |
| Agent roster: create, rename, retire, restore (H202) | admin `GET /api/admin/agents/roster`, `POST /api/admin/agents`, `POST /api/admin/agents/{agent_id}/rename`, `/retire`, `/restore` | ✅ agent dossier dialogs beside the SOUL editor; `nerva agents list\|create\|rename\|retire\|restore` | ⬜ no native roster editor; retired agents drop out of the shared agent list and routing for every client | H18.37 / H202 |
| Learning journey: list, show, edit, forget a learned entry (H046) | user `GET /api/dashboard/today/entries`, `GET /api/dashboard/today/entries/{entry_id}`; admin `PATCH` and `DELETE /api/dashboard/today/entries/{entry_id}` (cross `kg.write`); timeline entries on `GET /api/dashboard/today` carry ids | ✅ TODAY card edits and forgets a learned entry; `nerva journey` (aliases `learning`, `memory-graph`) | ⬜ the native Today board is not built yet (see the Today board row) | H18.37 / H046 |
| Skill delete in a batch, with the skill that absorbs it (H330) | admin `POST /api/skills/batch` takes `absorbed_into` on a delete (also with `dry_run`); the answer carries `references` (what moves to that skill, what still names the deleted one); `GET /api/skills/batches` lists them beside each proposed batch's diffs | ✅ Skill Batches panel shows each delete's references beside the diffs | ➖ owner desktop administration of skill batches; no native batch review planned | H330 |
| Usage and billing estimates (H220, local candidate) | admin `GET /api/admin/apm` adds measured local/cloud/unknown rollups; existing chat outcome carries selected current-turn usage and estimated cost | Usage/Billing panel, Command Center link and shared context/usage strip; pending integration acceptance | ⬜ no native aggregate spend/breakdown or new usage-detail renderer; existing shared backend governance applies | H220 |
| Optional repository skills and verified upstream import (H696/H334, local candidate) | user `GET /skills/hermes/catalog`, `GET /skills/imported`; admin `GET /api/skills/optional/catalog`, `POST /api/skills/optional/install`, `POST /skills/import`; pending approval requires the reviewed fingerprint | Skills Import displays tiers and exact catalog selection; generic imports collect immutable commit, entry and reference digests; current install and network decisions permit only quarantine for separate owner review | ➖ owner desktop skill installation; native read-only skill browser remains, no native install control or device acceptance claimed | H696/H334 |
| Curator lifecycle and recovery (H027, local candidate) | admin reads under `/api/curator`; typed preview/request; exact owner action decision applies the reviewed operation | `nerva curator` exposes all seventeen owner operations; the existing approval inbox decides queued cards; dedicated curator browsing remains CLI administration | ➖ owner CLI administration; no native curator control or physical-device acceptance claimed | H027 |
| Per-command access tiers and `/whoami` (H058) | admin settings key `commands.user_allowed_commands` (per channel, DM and group; fails closed to `/help` and `/whoami`); `/whoami` in chat; `GET /api/commands` lists only what the caller may run; denials answer `⛔ /<cmd> is admin-only here` and are audited (`slash_command_denied`) | ✅ the Admin settings editor (`PUT /api/admin/settings/commands`) writes the key; the web door and the channel adapters share one gate | ✅ inherited: native chat goes through the shared `/chat` path and the native command list (H18.26) reads the filtered catalog; no native editor for the setting is planned | H058 |
| Persisted LLM egress ledger (H381) | admin `GET /api/admin/network/calls` now serves rows that survive a restart | ✅ Network Monitor panel reads persisted and live rows | ➖ owner desktop administration; no native network monitor planned | H381 |
| Write legs on surfaces mobile already reads (notes, KG, memory decay) | `PUT /api/notes`, `POST /api/notes/rewrite`, `DELETE /api/kg/entities/{name}`, `POST /api/memory/decay/forget` | ✅ | ⬜ | |
| Block-tree note docs (DRA-53 `notes_store`, `NOTE DOCS` HUD panel — owner confirmed keep 2026-09-01) | user `GET/POST /api/notes/docs`, `GET/DELETE /api/notes/docs/{doc_id}`, `POST /api/notes/docs/{doc_id}/blocks` | ✅ | ⬜ | |
| Block-tree note blocks (edit / delete one block in a doc) | user `PATCH /api/notes/blocks/{block_id}`, `DELETE /api/notes/blocks/{block_id}` | ✅ | ⬜ | |
| Local docs index | user `GET /api/local-docs`, `POST /api/local-docs/index` | ✅ | ⬜ | |
| Nightly reflection (status + manual run) | `GET /api/reflection/status`, `POST /api/reflection/run` | ✅ | ⬜ | |
| Security skills browser (ATT&CK tactics → curated techniques, read-only) | `GET /api/security-skills/tactics`, `GET /api/security-skills/techniques` | ✅ | ⬜ | |
| Host dependency audit (H022) | host `nerva security [audit]`; admin `POST /api/security/dependencies/audit` performs governed OSV lookup for that host's submitted package identities | ➖ intentionally host CLI; a browser does not enumerate the host interpreter/MCP install | ➖ intentionally host CLI; no claim to audit the native app's installed dependencies | H022 |
| Prompt-injection scan | `POST /api/security/scan-injection` | ✅ | ⬜ | |
| Authentication audit events (H512) | Admin `GET /api/admin/audit`; typed guard/token lifecycle rows, including MCP RPC auth and successful MCP token signing (`surface=mcp`) | ✅ existing admin audit reader | ⬜ intentionally owner-HUD/CLI only in this local slice; native requests are logged server-side | H512 |
| Audit-chain verification (tamper-evidence read) | `GET /api/security/audit/intent`, `GET /api/security/audit/verify` | ✅ | ⬜ | |
| Channel pairing ceremony | admin `GET /api/channels/pairing`, `POST /api/channels/pairing/code`, `POST /api/channels/pairing/decide` | ✅ | ➖ admin ceremony run from the owner HUD (triage 2026-09-01) | — |
| Governed social drafts (draft-before-send) | `GET/POST /api/integrations/social` | ✅ | ⬜ | |
| Mic satellites (pair a device as a mic) | `GET /api/satellites`, `POST /api/satellites/register`, `DELETE /api/satellites/{satellite_id}` | ✅ | ⬜ | |
| Oracle sync and conflicts | user `GET /api/oracle/status`, `GET /api/oracle/conflicts`; admin `POST /api/oracle/sync`, `POST /api/oracle/conflicts/resolve` | ✅ standalone admin GETs carry the entered admin credential; existing POST paths are separate | ⬜ | |
| Packs inventory + verification | `GET /api/packs`, `GET /api/packs/{key}/verify` | ✅ | ⬜ | |
| World signals routing feed | `GET /api/signals/routed`, `GET /api/signals/agent/{agent_id}` | ✅ | ⬜ | |
| Market watchlist (owner-saved rows; no quotes, no trading) | `GET/POST /api/market/watchlist/saved`, `DELETE /api/market/watchlist/saved/{symbol}` | ✅ | ⬜ | |
| Onboarding wizard + funnel steps | `GET /api/onboarding/wizard`, `POST /api/onboarding/funnel` | ✅ | ⬜ | |
| Model setup — hardware tier → governed Ollama pull | `GET /api/onboarding/model-plan`, `POST /api/onboarding/model-pull` | ✅ | ⬜ | |
| Feedback · NPS (submit + admin summary) | `POST /api/feedback`; admin `GET /api/feedback/summary` | ✅ | ⬜ | |
| Kernel + north-star metric boards | user `GET /api/metrics/kernel`; `GET /api/metrics/north-star` (open) | ✅ | ⬜ | |
| Reasoning traces list | `GET /api/traces` | ✅ | ⬜ | |
| Cognition read + live scoring stream | `GET /api/cognition`, `GET /api/cognition/stream` (SSE) | ✅ | ⬜ | |
| Workflows (list / run / step-generate) | `GET /api/workflows`, `POST /api/workflows/run`, `POST /api/workflows/step/generate`; admin `DELETE /api/workflows/{pipeline_id}` | ✅ | ⬜ | |
| Sandboxed code execution | user `GET /sandbox/status`, `POST /sandbox/execute`, `GET /sandbox/kernels`, `POST /sandbox/kernels/reset` | ✅ | ➖ hub-host capability (runs on the hub box, not a phone surface; triage 2026-09-01, unchanged by K3 controls and H660 detached Docker/session stream spills — a resident interpreter is a property of the hub, and the reset button belongs where the code is written) | — |
| Agent templates (instantiate a config) | `GET /api/agent-templates` (open), `POST /api/agent-templates/instantiate` | ✅ | ⬜ | |
| Publish readiness (creative checklist + package) | `POST /api/creative/publish/checklist`, `POST /api/creative/publish/package` | ✅ | ⬜ | |
| Missions board (long-horizon governed workspaces) | `GET /api/missions`, `POST /api/missions/{mission_id}/{start,pause,resume,complete,cancel}` | ✅ | ⬜ | |
| Today board (daily digest) | `GET /api/dashboard/today` | ✅ | ⬜ | |
| Day report (redacted, shareable) | `GET /api/report/today`, `POST /api/report/today/export` | ✅ | ⬜ | |
| Proof-of-Action receipt | `GET /api/report/receipt/{audit_id}` | ✅ | ⬜ | |
| Natural-language schedule parser | `POST /api/schedule/parse` | ✅ | ⬜ | |
| Bench-agent learning + promotion | user `GET /learning`, `GET /learning/stats`; admin `POST /learning/promote`, `POST /api/learning/propose` | ✅ | ⬜ | |
| Heartbeats (per-agent run/start/stop) | `GET /heartbeat/status` (open); admin `POST /heartbeat/{agent_id}/{run,start,stop}` | ✅ | ➖ admin ceremony run from the owner HUD (triage 2026-09-01) | — |
| Transcript → tasks ingest | `POST /api/transcripts/ingest` | ✅ | ⬜ | |
| Escalation (ask-tier fan-out) | `GET /api/autonomy/escalation/targets` (open); admin `POST /api/autonomy/escalate` | ✅ | ➖ admin ceremony run from the owner HUD; the phone is the escalation *target*, not the fan-out control (triage 2026-09-01) | — |
| Agent dossier (soul + run history) | `GET /api/agents/{agent_id}/soul`, `GET /api/agents/{agent_id}/history` | ✅ | ⬜ | |
| Sub-agent steer + stop (H20.6) | `POST /api/subagents/{spawn_id}/steer`, `POST /api/subagents/{spawn_id}/stop` | ⬜ routes shipped, no HUD control yet — the Console SUB-AGENTS panel lists and spawns only | ⬜ | |
| Sub-agent spawn pause (H400) | admin `POST /api/subagents/pause`, `POST /api/subagents/resume`; `gate` on user `GET /api/subagents` | ✅ Console SUB-AGENTS panel (pause / resume, emergency-stop and kill-switch state) | ➖ admin ceremony run from the owner HUD | — |
| Local models + cloud auth profiles + VLM status | user `GET /api/vlm/status`; admin `POST /api/llm/{load,unload}`, `GET /api/llm/auth-profiles`, `GET /api/models/info`, `GET /api/models/local`, `POST /api/models/local/switch` | ✅ | ➖ hub-host capability (model lifecycle lives on the hub's GPU box; triage 2026-09-01) | — |
| System profile (read-only; selected via `JARVIS_SYSTEM_PROFILE`) | `GET /api/system/profiles` | ✅ | ⬜ | |
| Sentence-streamed TTS | `POST /tts/stream` | ✅ | ⬜ | |
| Eval datasets (run / compare / history) | user `GET /api/eval/datasets`, `GET /api/eval/datasets/{name}/{runs,compare}`, `POST /api/eval/datasets/run` | ✅ | ➖ | — |
| Bench stats | `GET /bench/stats` (open) | ✅ | ➖ | — |
| Remote room members (H658) | admin `GET /api/room-peers`, `POST /api/room-peers/invitations` (an approval card), `POST /api/room-peers/invitations/{invite_id}/bundle`, `POST /api/room-peers/members/{membership_id}/policy`, `DELETE /api/room-peers/members/{membership_id}`, `POST /api/room-peers/links`, `POST /api/room-peers/links/{link_id}/{call,renew}`, `DELETE /api/room-peers/links/{link_id}`; hub-to-hub `POST /api/room-peers/peer/{accept,call,renew}` (signed, pinned keys, NervaRoom grant) | ✅ Console REMOTE MEMBERS panel; `nerva rooms` | ➖ hub-to-hub capability administered on the hub; the phone decides the invitation and remote-call cards through the Approvals tab | — |
| File browser over approved folders (G21 · H142) | admin `GET /api/files/{roots,list,read,download}`, `PUT /api/files/upload`, `POST /api/files/{mkdir,rename,delete}` (rename/delete queue an irreversible-tier approval card) | ✅ Console FILES panel | ➖ hub-host capability (the owner's disk on the hub box); the phone decides the rename/delete cards through the Approvals tab | — |
| Owner event hooks (G17 · H163/H514/H021/H408) | admin `GET /api/hooks`, `POST /api/hooks`, `POST /api/hooks/{id}/{disable,enable,test}`, `DELETE /api/hooks/{id}` (defining or re-enabling queues an irreversible-tier approval card) | ✅ Console HOOKS panel | ➖ hub-host capability (programs on the hub box); the phone decides the `hooks.define` cards through the Approvals tab | — |
| Channel settings (G21 · H151) | admin `GET /api/admin/channels/config`, `PUT /api/admin/channels/{channel_id}/config`, `PUT /api/admin/channels/{channel_id}/secret`, `DELETE /api/admin/channels/{channel_id}/secret/{name}` | ✅ Console CHANNELS panel | ➖ admin ceremony run from the owner HUD (channel tokens are typed on the hub host) | — |
| Restart and update check (G21 · H160/H173) | admin `GET /api/admin/ops/update`, `POST /api/admin/ops/update/fetch`, `GET /api/admin/ops/actions/{action_id}`, `POST /api/admin/ops/restart` | ✅ Console RESTART / UPDATE panel | ➖ hub-host capability (restarting and checking the hub's own checkout belong to the owner HUD) | — |
| Trusted update, verified restart and rollback (H624) | admin `GET /api/admin/ops/update/plan`, `GET /api/admin/ops/update/receipts`, `POST /api/admin/ops/update/apply`, `POST /api/admin/ops/update/rollback`, `POST /api/admin/ops/update/trust` | ✅ Console RESTART / UPDATE panel (plan, request update, request rollback; trust via `nerva update trust`) | ➖ hub-host capability (the cards are accepted in the decision inbox like any other) | — |
| Nerva Workspace (B2B pilot app: company accounts, departments, documents, assistant, reports, approvals, admin console) | `GET /workspace`, `GET /workspace/{path:path}` (the app shell); `/api/workspace/*` behind the workspace's own session cookie (tiers `ws_user`/`ws_admin`), all 404 unless `NERVA_WORKSPACE=1` | ✅ separate web app at `/workspace`, not a HUD panel | ➖ Nerva Workspace: web only, no native surface (intentional) — company employees use the responsive web app (usable at 360 px); the owner's native apps never sign in to it | — |

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

> **Triage (owner, 2026-09-01):** exactly five of the ⬜ rows above are marked ➖ desktop-only, each
> with its one-line reason in the Mobile cell — Sandboxed code execution and Local models + cloud auth
> profiles + VLM status (hub-host capabilities), Heartbeats, Channel pairing ceremony and Escalation
> (admin ceremonies run from the owner HUD). The remaining 33 ⬜ rows at triage time (plus the two
> block-tree notes rows added the same day under DRA-18/DRA-53) stay tracked-but-unscheduled with
> empty Task cells: none is ported — no native screen, no client call, no partial — and an `H18.x`
> id is assigned only when a design partner asks for that surface on the phone.

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


<!-- models-context-2026-09-15 -->
Model/session context: backend clock and request shaping apply across channels. Existing /admin metadata exposes compatible provider/model, explicit cache/effort capability toggles, per-model vocabularies and Ollama num_ctx. Dedicated mobile/HUD model controls remain a UI gap; no new routes or mobile controls are claimed.

### H178 native floating chat — 2026-09-15

Desktop-only: Tauri tray/main controls open a frameless chat using the existing HUD
conversation and authentication; geometry recovery and handoff are implemented.
Mobile retains its normal chat. macOS host validation covers the bounded window
surface; Windows/Linux, compositor-exclusive overlays, transparency/frost, click-through,
global shortcuts, move-to-pointer and underlying-window capture remain unverified or unimplemented.
See `desktop/README.md`; full Hermes H178 remains partial.

### 2026-09-15 — H146/H449 advanced automations
HUD Jobs now provides custom action creation/edit, visual schedule controls, sixteen typed
blueprints, repeat limits, per-job channel/history delivery, diagnostics and notepad editing.
Native mobile authoring remains a gap; use the responsive web HUD. New admin operations are
GET /api/jobs/doctor, GET /api/jobs/incidents, POST /api/jobs/tick and
PUT /api/jobs/{job_id}/notepad. Mobile has no new adapter and no live delivery was enabled.

H146 followup: the topbar Automations entry now opens a roomy dedicated Jobs workspace;
Console integration remains. Custom creation uses a native modal with initial focus,
Tab containment, Escape/cancel and focus restoration. Browser proof uses mocked job reads;
no live channel was enabled. Generated OpenAPI types now include all four added job routes.

2026-09-15 — H12.26 binary attachments: desktop Artifacts supports opt-in upload,
validated authenticated delivery, pin/delete. Native mobile attachment controls
remain a parity gap; existing text Canvas is unchanged.

2026-09-15 — H515/H518 desktop supports configured local backend/model selection, reference blending, 2× bicubic upscale, unified gallery and ZIP export. Native mobile generation/gallery parity remains open; no cloud or device validation claimed.

2026-09-15 — H684: existing admin GET /api/jobs/doctor includes health and persistent execution/delivery outcomes. Responsive web Jobs renders the report. Native mobile has no dedicated health view; that parity gap remains. Diagnosis triggers no repair or delivery.

H129 (2026-09-15): responsive HUD routes are bookmarkable at /v2/<mode> and /v2/console/<panel>. Pixel 7 Chromium navigation is verified with a stubbed backend. This does not add native mobile navigation or a cross-profile route registry.

### 2026-09-27 — H487/H513 approval grouping and provider consent

Responsive web Decision Inbox and legacy Actions accept bounded human reasons and
group verified owner submissions. Individual approval remains single-use; explicit
group rejection uses a current membership snapshot. Telegram shows group counts and
collects a reason after rejection. Native mobile has no new grouping/reason controls.

The responsive web Security Posture panel displays provider data-handling policies,
persistent warnings, and audited configuration-bound unattended-use consent/revocation.
Native mobile has no consent-management surface; use the web panel. No native-device
acceptance or external provider call is claimed by this offline increment.

Approval-judge consent is a separate responsive-web row, keyed to its configured
model, destination and credentials. It does not enable remote judging. Native mobile
still uses the web panel for consent management; no native acceptance was run.

Video analysis (H277, 2026-10-02) adds a separate consent row to the responsive web
Security Posture panel and uses existing Decision Inbox task approvals. Configured
video fallbacks have separate consent/revoke controls in that web panel. Native
mobile has no video source picker, role editor, or dedicated video-consent control;
use the responsive web panel for consent. The primary transient-retry and valid-empty
full-chain retry settings have no native editor. Their additional send budgets are
shown through the existing server-generated task approval notice. Native-device and live video-provider acceptance
remain unverified.

OpenRouter native video (2026-10-04) uses those same responsive-web task/role
consent surfaces. Provider privacy preferences are server-side and bound to the
approval; there is no new native mobile editor or video picker. Offline tests do
not establish native-device or live/model acceptance.

Local auxiliary model selection (H277, 2026-10-02) runs on the server for session
titles, recall rewriting, conversation review, compression and governed acquisition
capability/plan generation. Existing results reach the same clients; the six
`JARVIS_AUX_*_MODEL` environment settings have no native editor. Acquisition uses
its existing governed server workflow; no new native acquisition UI is claimed. A structured LM Studio temperature rejection can now recover on these nonstreaming server calls; no native configuration control or device proof was added. This adds no native-device or live-model acceptance claim.

The optional governed image empty-retry budget is shown by the responsive-web
composer before sending and by the local describe/screen panels. A changed budget
invalidates old destination confirmations and unattended role grants. Native mobile
has no editor or verified rendering for this server setting; native acceptance is
still open. Existing camera and Telegram roles retain their local-only boundaries.
Native vision responses now prefer normalized visible text and can use structured
reasoning when that text is absent, including thought text from Gemini video. The
existing responsive-web answer surfaces receive this server-normalized text; no
new native UI or native-device acceptance is claimed. Normalization adds no model
call or consent grant.

The responsive-web image composer now displays provider-policy warnings alongside
the reviewed destination and successful answer. Its request-scoped remote
acknowledgment is unchanged. Native image-policy warning parity remains open;
the local embedding guard has no new native control or remote-consent surface.

The responsive-web Decision Inbox displays an optional task approval deadline.
Authoring is the existing owner-authenticated task API; omitted deadlines preserve
indefinite waiting. Native deadline authoring/display is not added in this slice.
Expired tasks and failed unanswered-approval outcomes remain visible through the
existing task/work-run APIs. No native-device acceptance is claimed.

Responsive-web image description and screen reflex now show policy warnings and
require a local VLM on the Nerva server. The obsolete remote acknowledgment in
the legacy describe panel is removed. Status exposes a sanitized origin; failed
or empty inference is not a successful answer. Native equivalents of these policy
warnings and controls remain open; this slice has no native-device acceptance.

Responsive-web Trust includes separate allow/revoke controls for Telegram image
descriptions with unknown or training policies. This acknowledgment neither grants
remote image access nor changes household camera consent. Native role controls and
live Telegram/device acceptance remain open.

Responsive-web Trust also exposes the separate camera-description model-data role.
Acknowledgment is independent of household consent and does not enable capture or
remote inference. Native camera role controls, supported owner camera provisioning
and live-device acceptance remain open.


Explicit OpenRouter image analysis (H277, 2026-10-02) is available through the
responsive-web composer and native VLM backend, with live upstream routing
controls bound to each preview/request. Native mobile image intake and these
provider controls remain a gap; existing mobile chat does not gain image routing.
Responsive-web image drafts additionally support distinct per-turn training/cost
confirmations with audit and destination binding; native mobile has no equivalent
image intake or confirmation controls yet.
Signed OpenRouter video is not delivered.

Explicit DeepInfra image analysis uses the same responsive-web composer and
confirmation controls. Its Refresh vision destination button can refresh the
server-side model catalog. This adds no native image intake or native mobile
provider configuration; native-device and live-provider acceptance remain open.

Nous account lifecycle now has owner-only server routes and a terminal device-code
flow. No responsive-web or native-mobile login controls are added in this
prerequisite. Account login does not enable a model route. Explicit Nous vision
now uses the responsive-web image composer with account-bound recommendations,
Chat/Messages inference and the existing destination/training/cost confirmations.
UI account management, native image intake and native-device acceptance remain open.

Opt-in automatic image selection now works in the responsive-web composer:
the chosen OpenRouter, Nous or DeepInfra provider appears with its model and
destination before consent, and a changed choice invalidates that consent.
The composer has no actual selected main conversation route, so this first
candidate is absent. Native mobile image intake and provider controls remain
open; this web flow does not imply native mobile parity.
The web composer now prepares a short-lived, one-use destination review for
the current image question and agent. Editing either clears its confirmation;
a changed destination or reused review is refused before image egress. This
still uses the configured vision route, not the selected chat backend. Native
mobile has no matching review flow.

Selected main image conversation turns (H277, 2026-10-02) now use the
responsive-web composer to commit the reviewed question, an image-count marker,
and the selected model's answer to the shared session. Reload restores the
answer and bounded provider provenance from server memory; image bytes remain
transient. Explicit standalone and auxiliary image descriptions still use the
separate transient route. Native mobile has no image composer, reviewed
destination flow, or equivalent history rendering. This gap remains under
H18.10 pending a native client request; the web behavior is not native parity.
# H595 code interruption checkpoint (2026-10-05)

The existing authenticated chat endpoints accept a same-session new message while
code runs and return the prior tool's interrupted result after teardown. No route
or mobile schema was added. Native mobile producer/interaction acceptance is not
verified in this batch. The responsive HUD now submits typed follow-ups during a text stream and keeps
separate reply ownership and cancellation. This browser behavior does not
establish native-mobile producer or interaction parity.


## FAL image provider (2026-10-06)

The existing authenticated media generation route and registered image tool now
accept `cloud=true, backend=fal`. Generation and model-bounded edits from FAL
media URLs produce the same opaque local artifacts after approval. Native mobile
has no FAL configuration, model picker or reference URL entry UI; this backend
addition does not establish native interaction parity.


## OpenAI/Codex image providers (2026-10-06)

The shared authenticated media API now supports approved OpenAI Image2 tiers and
native Codex image generation/edit from saved artifact IDs. The desktop Images
HUD selects OpenAI, Codex and FAL models/references. Native mobile has no equivalent
provider/model/reference controls or managed Codex OAuth flow; these remain gaps.
No mobile device or live subscription generation was validated.

## Additional image providers and Krea continuation (2026-10-06)

Krea Enhance now has an additive authenticated `enhance_task_id` operation and
`enhance_available` task field. The responsive HUD proposes a separate 2x pass,
keeps the original preview, displays the bound source in Decision Inbox and
resumes interrupted Enhance jobs through a fresh GET approval. Validated 4K
Enhance pixels have proof-bound download/gallery/export admission. Native mobile
generation/gallery/Enhance producer parity and device acceptance remain open.

The existing authenticated media API supports OpenRouter, Krea, xAI and dynamic
DeepInfra catalogs through separate approved tasks. Krea recovery queues a fresh
GET for an existing job; DeepInfra discovery queues a catalog GET before image
generation becomes available. The responsive Images HUD exposes these controls.
Native mobile has no equivalent provider/catalog/continuation interface. No
native-device or live-provider acceptance is claimed.

The 2026-10-09 local HUD contrast candidate moves secondary browser text away from
the decorative `--ink-3` token. It changes no native API or interaction; native
screens use their own theme and require separate contrast/device evidence. See
`docs/hud-muted-text-contrast-20261009.md` at the repository root for measured
browser scope and exclusions; no full native accessibility claim is made.

Browser accessibility readiness (2026-10-09): the HUD Admin EstopCard exposes its pending state to assistive technology and its browser scan. This changes no native endpoint or control; native device accessibility remains separately unverified.

## Named compatible endpoints (H367, 2026-10-29)

The owner desktop HUD has Console → Admin → Custom Endpoints and the CLI has `nerva provider custom`. Ten admin-only routes under `/api/admin/llm/custom-endpoints` manage named entries, activation/clear, validation and endpoint credentials. Native mobile has no corresponding configuration or secret-entry surface; this remains owner desktop administration. The generated desktop route manifest includes the new panel, with floating chat routes unchanged. Local source/frontend tests do not establish a native GUI, physical-device or live endpoint result.

## Governed fresh-profile browser sessions (2026-10-29)

The desktop Operator exposes owner-approved start/act/close and grounded refs with bounded admin-only session/task projections. Native mobile has no equivalent browser session controls and no owner-profile access. The local Mac Chrome fixture verifies source behavior, not physical-device/live-Hub acceptance. Advanced browser/profile/engine requirements remain separate.


H396 whole-turn outcome (2026-10-29 local source): browser cockpit/focus chat now reads
one request-owned JSON/SSE outcome and live progress for consolidated source reasons,
pending-tool WARNING, distinct proposal/queue/execution counts, observed or explicitly
estimated output flow and path-free failed-unsuperseded file attempts. Signed task/turn
origins and effect-boundary verification support the footer; late approvals cannot
rewrite a closed turn. Native mobile retains its validated latency-only H18.33 strip.
The new explanation, tool/output accounting and mutation footer are an explicit native
surface gap; no physical-device/live-Hub acceptance is claimed.

Browser observations (2026-10-29 local source): Operator queues separate approved
console/get_images reads and renders bounded untrusted completed-task observations.
The owner-only task projection retains strict session/registration/Kernel checks;
reads do not fetch image bytes or authorize actions. Native mobile has no corresponding
observation or session controls. Vision/dialog/JS/CDP, saved profiles and the other
advanced browser requirements remain open.


2026-11-12 local continuation v5: shared chat handlers add owner /egress, /reload-mcp, /diff and /profile, plus /version. No dedicated native-mobile or HUD maintenance panel was added; live-device acceptance remains unrun. /diff session and saved-config MCP reread remain unsupported. Native provider menu descriptions are sanitized before truncation and unsafe command identifiers are withheld. See docs/hermes/evidence/2026-11-12-local-continuation.md for tested scope.

2026-11-12 local continuation v6: owner shared chat now exposes failed-channel `/platform` controls and `/update` approval intake. No dedicated HUD/native-mobile maintenance UI was added; no device/live-channel acceptance is claimed. Update intake still refuses in strict Kernel mode until exact registration exists, and requester progress/restart notifications remain open.

2026-11-12 local continuation v7 supersedes the v6 strict-intake limitation: exact hub.update mediation is implemented with current signed/human/AUTO execution checks; no dedicated maintenance UI or live-device proof is added. /pause recovery spelling and confirmed Slack/Discord disconnect controls share the existing chat surfaces. Requester update progress/restart notification and other recorded gaps remain.

2026-11-12 local continuation v8 supersedes the earlier saved-MCP reread gap: shared owner chat now previews and confirms exact saved-config reconciliation. Boot load-set and owner disconnect intent persist; new servers remain disconnected. The confirmation is one-time and expires; no permanent always preference or dedicated native mobile/HUD panel is implemented. Provider/device reconnect acceptance remains unrun.

2026-11-12 local continuation v9: owner chat `/diff session [--stat]` now reads the earliest retained full-project terminal checkpoint against current allowed project files. Explicit approximation/exclusions and missing/corrupt-history refusals; no Git required. Existing chat command surface only; no dedicated checkpoint-diff UI or live mobile/device acceptance claimed.

2026-11-12 local v10: existing owner `/update` chat/approval flow now reports pending-or-running when the shared queue atomically refuses another executable update card. No dedicated UI change; requester progress and post-restart notification remain open, and no live mobile/device acceptance is claimed.

2026-11-12 local v11: keyed channel replies and Telegram/Discord attachments now withhold transport when a durable claim cannot be obtained; shared-database claims and recovery are conditional/atomic. Recent keyed evidence has a500protected-row quota for24h, with new keyed claims refused on capacity. Existing receipts API remains; no new receipt panel/mobile UI or live device acceptance in this slice.

2026-11-12 local v12: HUD Admin Channels now has a lazy owner-only Delivery receipts disclosure with recent50 metadata rows, retained counts, explicit uncertain outcomes and manual refresh. It reads the existing authenticated endpoint, bounds response data, hides stale results on failed refresh and has no send/retry/clear controls. This closes the HUD receipt-reading gap only; native mobile receipt UI, live device/platform acceptance and dead-target-clear UI remain open.

2026-11-12 local continuation v13 (H084 prerequisite): ephemeral restart admission/drain counts existing work and refuses fresh job/subagent/turn starts before claims or budgets; emergency commands retain owner checks. No restart endpoint/command or mobile/HUD restart behavior added. Worker admission, signed completion, physical restart and requester notification remain open; full restart is not claimed.

2026-11-12 local v14 (H084 prerequisite): worker admission covers ordinary/consent/owner-once claims, and original Telegram owner-DM command provenance carries bot-scoped provider identity through paired inbox to registry. No restart command/effect or new HUD/mobile endpoint yet; signed completion and requester notice remain open.

2026-11-12 local v15 (H084): original owner Telegram /restart now creates an exact signed human-approval card. Atomic DONE completion precedes a one-use physical claim, bounded drain and late authority checks; a different boot may attempt one fixed keyed same-owner availability notice. No real restart or Telegram send was performed. Service-manager/provider acceptance remains open; this is a chat-only command with the existing approval surface, no new HUD/mobile endpoint. Supersedes the v14 command/completion/notifier implementation gaps; full H084 remains partial.

2026-11-12 local v16 (H084): bounded private Telegram restart phrases route to the fixed owner command before pending input and conversation context. Original inbox text is preserved and signed in v2 source tickets; historical v1 literal commands remain verifiable. Only the verified original human control intent receives scoped manual classification for signed intake; generic taint and human approval stay enforced. Group prose and other services are unchanged. Historical boot cleanup works with execution disabled without granting a stop or send. Full real ingress/Kernel/approval/DONE pipeline uses a mocked stopper; live acceptance remains open.

2026-11-12 local v25: Mobile Status adds an opt-in Delivery receipts disclosure backed by the existing owner-guarded endpoint. It validates and projects at most50 metadata rows, explains retained counts and uncertain delivery states, and offers refresh/close only. No fetch before opening; connection/credential changes remount closed and erase owner data. Refused refresh, close and unmount clear/abort/fence stale results. No resend or dead-target mutation. Native TypeScript and full mobile Jest are now verified locally; real device/platform acceptance remains open.

Local V51 signed-extension restart routing is a backend lifecycle change shared by chat command surfaces. Mobile's existing extension inspection remains read-only; admin activation/revoke and persistence warnings are available through the existing API/CLI, not new mobile controls. No device acceptance or mobile mutation parity is claimed for this lot.

H697 local continuation (2026-11-13, V53): browser startup and desktop conversation invalidation now share recovery only for the exact requested-session-missing 404. Existing authenticated `/memory` supplies a replacement; request/selection/turn generations fence late responses, and transient/authorization/history refusals preserve selection. Native mobile terminal-pull recovery is not implemented by this change; its existing scoped session persistence remains separate. Reclaimed-session push integration and live desktop/device acceptance remain open.


2026-11-13 local V55 (H624/H695): existing updater status/receipts expose `data_restore_staged` separately from `data_restored`; private archive identity stays hidden. Required data restoration is confirmed only by an exact successful backup result. The existing host-maintenance surfaces retain their scope; no new HUD/mobile restoration control or live device acceptance is claimed.


2026-11-13 local V56 (H624/H695): updater receipts distinguish `stash_restored`; refused or failed automatic owner-stash replay provides recovery guidance through the existing maintenance status. No new HUD/mobile controls or live device proof; host-only maintenance scope remains.


2026-11-13 local V57 (H695): host updater/bootstrap refuse unsafe POSIX venv mutation with named diagnostics through existing logs/errors. No new HUD/mobile controls. Windows ownership is explicitly unchecked; device/native ACL acceptance remains open.


2026-11-13 local V59 (H697, still partial): mobile now offers explicit Start new chat after an exact selected-session-missing response. The unsent message persists until Add to draft or Dismiss; adding preserves newer composer text and never sends automatically. A per-turn server marker confirms successful governed /new before selection changes. Older hubs without that marker preserve the old selection and show guidance. Authorization, busy/corrupt/network errors and stale owner/selection responses cannot trigger recovery. Native device acceptance, automatic terminal-pull and reclaimed-session push remain open.


2026-11-13 local V60 (H141/H195, still partial): mobile History adds a local filter over loaded recent conversations by title, summary, session identifier and agent. Search scope is explicitly limited to the loaded recent list (the current API returns up to 20 rows); it is not full-history or transcript search. Clearing restores the list, refresh retains the query, closing or changing connection resets it, and choosing a match still explicitly resumes its lineage target. Browser search/paging, full-history indexing and live native acceptance remain separate.


2026-11-13 local V61 (H141/H195, still partial): web Sessions now exposes all loaded recent rows instead of silently truncating the list to12. Local title/summary/identifier/agent filtering has explicit loaded-list scope, clear and no-match states; tab changes reset the query and query changes dismiss pending rename/delete confirmation. Existing governed session actions remain explicit. The API still returns up to20 rows; full-history transcript indexing/pagination and device acceptance remain separate. Mobile loaded-list search was already implemented in V60 and is unchanged.


2026-11-13 local V62 (H141/H195, still partial): owner web history now loads older sessions beyond20 through a bounded keyset API. Pages retain archive/lineage filtering and deterministic date+ID ordering; local search covers all loaded pages. Failed later pages retain the list and support retry; stale requests cannot cross tabs/reload. Guests and older hubs retain the recent-list fallback. Mobile pagination, full-text indexing and live device acceptance remain open; pagination is not a fixed historical snapshot. Existing mobile GET/sessions stays unchanged; web initial owner-route refusal can use the independently authorized legacy recent list.


2026-11-13 local V63 (H141/H195, still partial): mobile History adopts the existing owner keyset API and explicitly loads older conversations. Local search includes all loaded pages; retry preserves rows after later failures. Initial401/403/404/405 alone falls back to the legacy recent list. Refresh, close, connection changes and explicit resume fence late responses. No backend or Windows changes; physical-device acceptance and full-text indexing remain open. Guest/older-server fallback remains recent-only; no live device or deployment claim.

2026-11-13 local V64 (H141/H195, still partial): owner web Sessions adds per-row retained-text preview and explicit JSON download without resuming, changing the default session or unarchiving. The admin-only read uses existing identity, turn-lease, import and rewind fences; bounds and automatic secret redaction fail closed. Only retained user/assistant text is included, not compacted archives, tool/media/system content. Mobile preview/export, full-archive export and live device acceptance remain separate.

2026-11-13 local V65 (H141/H195, still partial): mobile History adds explicit retained-transcript preview separate from resume and user-initiated JSON save to the app documents folder. It uses the existing owner-only V64 read with strict exact-session/schema/UTF8-size validation and a field whitelist. Close, search, refresh, resume and connection changes retire private preview/save status. The UI states retained-only automatic redaction; full compacted archives, external sharing and real-device acceptance remain separate.

2026-11-13 local V66 (H141/H195, still partial): web and mobile history add conjunctive agent/date filters over loaded metadata and adjacent local-day group labels without reordering keyset results. All/exact/unassigned agents and all/last7days/last30days/unknown dates are explicit; reset, pagination and retained-transcript privacy fences are preserved. This is loaded-history navigation; full-text/source filters, server-wide filtering and live device acceptance remain separate. Legacy complete archive export is blocked by missing instance/branch provenance and incomplete capture; old logs must not resurrect rewound messages.

2026-11-13 local V67 (H005, still partial): `nerva sessions transcript ID [-o PATH]` exports the owner-authorized V64 retained-current-history JSON with strict identity/schema/UTF8 bounds and a field whitelist. Stdout contains JSON only; diagnostics are generic on stderr. File output is owner-only and create-only, published from a flushed temporary file without clobbering existing files or symlinks. Existing opt-in training `sessions export` is unchanged. Full historical capture/archive, JSONL and other session administration remain separate. This is CLI parity with existing web/mobile retained JSON, with no endpoint or UI change.

2026-11-13 local V68 (H005, still partial): CLI session organization adds rename, pin/unpin, archive/unarchive and archived listing through existing protected routes. Inputs are checked before requests, titles use backend normalization, and strict exact-session/action receipts prevent false success. Malformed success receipts report that the change may have applied; no automatic retry. JSON output includes only known receipt fields. Existing lineage/import ownership, transcript/trajectory exports and default listing are preserved; delete/prune and full historical capture remain separate. CLI parity only; existing web/mobile behavior and endpoints unchanged.

2026-11-13 local V69 (H005, still partial): `sessions history` adds bounded owner keyset traversal beyond the recent20 list, with exact-agent/unassigned, age and loaded metadata query filters. Explicit result/page caps, cursor continuation and stop reasons distinguish exhausted pages from a partial scan. Strict bounded whitelisted pages, dedup/order preservation and buffered output refuse malformed/repeated cursors or late failures without false completion. Default recent listing and existing session mutations/exports remain unchanged. Filtering is client-side within the scanned pages; source/tool-call filters, interactive browse and fixed snapshot isolation remain separate. CLI-only parity; existing UI/endpoints unchanged.
