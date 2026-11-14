# HUD v2 — Remaining work (next PR)

Local gateway continuation, 2026-11-12: native Slack slash commands and the
`/nerva` fallback use the existing command access, inbox and approval surfaces.
This is host/Slack-specific behavior; it adds no HUD endpoint or screen. Workspace
configuration and live Slack acceptance remain external prerequisites.
Native Discord commands likewise use existing inbox/approval surfaces; health
reports registration/hidden counts. Live Discord acceptance is unrun. The
`channels.max_inbound_media_bytes` limit uses existing generic admin settings;
no dedicated media control or frontend/device acceptance is claimed.

H079 single-skill slash loads and `/commands [page]` use existing chat surfaces.
Local V24 extends the HUD command catalog with owner-only quick commands,
web-enabled unambiguous skills and explicit `/bundle <slug>` entries. It shows fixed
metadata and partial/truncated notices without executing or loading skill bodies.
The combined catalog is capped at256 rows, registry first; skill inventories over512
are omitted rather than resolving against an incomplete pool. H069 now tests App SSE final replacement (including empty final); device acceptance
is unrun. Main chat SSE labels/prose use outbound safety; opaque secret redactors
withhold incremental prose until whole-response verification.

Owner `/reload-skills` uses the shared chat registry and existing command catalog;
no dedicated reload screen is added. Telegram static sticker caption/cache is a
host channel feature. Native/mobile media and reload acceptance remain unrun.
Owner `/debug` returns a local report path through existing chat; it has no upload
or new screen and currently refuses on Windows. Discord attachments use existing
inbox/approval cards; native provider acceptance is unrun.

Local candidates, 2026-11-03: H220 adds Usage/Billing estimates, measured
local/cloud/unknown aggregates, a Command Center link, and current-turn usage
in the existing shared context strip. Explicit owner field selections remain
unchanged; fresh defaults expose the context meter. Historical usage without
route evidence remains unknown, and unpriced cost is not presented as free.
H696 adds bundled/optional catalog tiers and explicit installation of optional
repository skills into quarantine. Native aggregate usage and native skill
installation controls remain gaps; integration acceptance is still pending.

H334 local import update (2026-11-04): Skills Import uses current admin and
kernel admission, with immutable commit, entry and reference digest fields for
generic sources. The built-in Hermes selection uses its server-owned pin.
Grant and queue responses identify a quarantined copy awaiting separate owner
review. No native install control or live upstream acceptance is implied.

H027 local candidate (2026-11-04): `nerva curator` and the admin `/api/curator`
domain expose lifecycle inspection, exact reviewed owner requests and recovery.
The existing action approval inbox decides curator cards; the CLI prepares their
targets and reports pending until approval actually applies them. There is no
dedicated curator browser panel or native control. Dry-run requests do not queue
or mutate. Full H027 integration is still pending; no new capability credit is
claimed from wiring alone.

SEC-B6 local client/security source (2026-11-03): twelve content-bearing GETs
now require user access: `/api/oracle/status`, `/agents`, the three
`/api/eval/datasets` list/runs/compare reads, `/learning/stats`,
`/api/local-docs`, `/skills/imported`, `/api/arena/leaderboard`,
`/api/metrics/kernel`, `/api/metrics/capabilities`, and `/sandbox/status`.
Existing v2 `apiGet`/`useApi` callers send the user token; legacy v1 reads use
the stored-token fetch wrapper. That wrapper now resolves URL origin and copies
request options/headers per local attempt, preventing its token injection from
following protocol-relative external URLs or reused options. The standalone
`/admin` page does not load that wrapper: its Agents and Oracle status/conflicts
GETs use the existing admin-token `afetch` helper. Admin credentials satisfy
user-read guards. This is a read-access change; existing mutation contracts
remain separate.

The successful public `GET /api/security/kill-switch` is an exact three-field aggregate:
`{global, any_halted, halted_count}`. Scope names and reasons are available on
admin-only `GET /api/security/kill-switch/details` as `{global, halted}`. Trust
and Console distinguish a global halt from scoped halts; the global button
still acts only on global scope. Missing, failed, and contradictory aggregates
show unknown and preserve the safe engage direction. Trust also remains
unknown when a successful POST cannot be verified by a subsequent GET. Mobile
consumes only the aggregate in a read-only Status row, with the same global,
scoped, and unknown distinctions. Focused source tests and typechecks support
these claims; a served browser, credentialed network Hub, and native device
have not been accepted in this documentation slice.

> What's intentionally **left out** of the P0–P6 build (PR #156 / merged to `main`) and queued for
> the next pass. **Update 2026‑06‑08: the cutover happened — V2 is the default HUD at `/`** (legacy
> at `/v1`, override `JARVIS_HUD=v1`); §8 below is done, the rest is the depth punch‑list.
> Companion: `HUD_V2_IMPLEMENTATION_PLAN.md`, `HUD_V2_COVERAGE_AND_PLAN.md`. Generated 2026‑06‑05;
> **re‑audited 2026‑06‑10** (see §10).

H456 local candidate (2026-10-10): the shared web Jobs form adds requested
reasoning effort and the installed tool catalog. Existing Settings controls
author the cron default and operator restrictions. These do not close the
separate operations/context controls below or native-mobile authoring.

H453/H454 local candidate (2026-10-10): CLI/admin API can configure cross-job
`context_from`; complete safe script stdout is separate from bounded history and
context excerpts. Dedicated web source selection, latest-output inspection and
continuity controls remain open. Existing diagnostics and legacy note editing do
not constitute those controls. See `docs/automations-operations.md`.

H015 local candidate (2026-10-10): admin API/CLI add durable incident acknowledgement,
named job notes, explicit continuity and historical runs after job removal. The
current Jobs panel shows incident JSON and retains its legacy note editor. Dedicated
acknowledgement, KV, continuity and deleted-job history controls remain open; no new
web control is claimed. See `docs/automations-operations.md`. H049 named log reading
is a host CLI capability; the existing web Logs selector remains supported.

H002 local candidate (2026-10-10): JSON chat replies and SSE end events add a
request-owned generation-usage snapshot. Existing HUD chat rendering is retained;
this batch does not add a spend panel. Atomic usage-file export belongs to the
host CLI. Generated API types include the additive field and the earlier H441
resume/import routes. See `docs/cli-chat-receipts.md` for measured, estimated and
unknown values.

H660 (2026-09-15): session kernels now use detached Docker internally. Existing
sandbox status/reset controls remain the operator surface; backend status labels
identify `docker-detached`. Complete Python cell streams use existing tool-result
file references. Failed teardown stays visible as unconfirmed; reset can be retried
without claiming the worker is gone. Real Linux and native macOS Docker tests now
pass, including reset/cancellation and context/proxy isolation; SSH/Modal/TLS
provisioning remains open. See docs/hermes/evidence/2026-09-15-docker-containment.json.

## 0. Do this first

H441 local candidate (2026-10-10): owner CLI/API selectors and Claude Code/Codex
transcript imports extend the existing free Sessions recap. Imported/derived
sessions are owner-only at the shared server boundaries; guest session and
checklist lists omit them. Browser import/selector controls are not added in
this batch. Foreign source discovery remains CLI-host administration; see
`docs/foreign-session-resume.md`. H398's fixed completeness notice and internal
risk advisory affect model tool results, with no new public chat field. H667's
existing temporary-directory setting now describes standard environment fallback.

H329 local update (2026-10-10): Skill Switches renders HTTP 202 as pending
owner approval and retains the disabled state until the worker applies the
exact request. Global and channel settings remain distinct. Canonical approver
audit is transactional; the IntentLog projection is optional. Missing or corrupt
state returns an unavailable response. The existing approval inbox is the
review surface; the interactive `nerva skills config` picker uses the same API.
H299/H397 default to guidance with an explicit runtime setting for stall stops.

H413/H689 local update (2026-10-10): existing Sessions displays retain instant
and background-upgraded titles; automatic naming now uses a dedicated small
local model. An unavailable model keeps the instant title. Profiles share the
installation identity while their stores and credentials remain isolated.
Existing node-registration and sender-link APIs return 503 when identity is
unavailable; reconciliation and re-pairing remain host administration, with no
new identity-repair panel. See `docs/install-identity.md` and
`docs/plans/2026-10-10-hermes-closure-02.md` for migration and verification limits.

H256 local update (2026-10-10): existing owner consent actions refuse corrupt
settings before audit or grant/revoke, including the preflight-to-lock race.
The existing error response remains the UI boundary; no repair panel is added.

Session ID validation (local backend candidate, 2026-10-09): existing chat and
session routes reject a terminal newline through the corrected shared validator,
before session or memory work. Valid IDs keep their exact value; no new HUD
control or response schema is needed. See docs/project-session-id-validation-20261009.md.

Media catalog integrity (local backend candidate, 2026-10-09): new cloud-completion, ComfyUI and local OpenAI PNG catalog rows carry their producer SHA-256 checked on `md-*` delivery/export. Gallery previews remain metadata hints until download; export metadata distinguishes verified and unbound rows. No new HUD control or native negotiation is added, and legacy/other unsupplied producer rows plus standalone generated URLs remain outside this digest binding. H477 stays partial.

Client protocol discovery (local candidate, 2026-10-09): `GET /v1/capabilities` now exposes the mounted chat/session wire contracts for external clients. This is a machine-readable API, with no new HUD control; existing browser and native transports keep their tested contracts. Live readiness remains `/api/capabilities`, and `/v1` remains the legacy HUD. Wider API discovery and compatibility negotiation remain open under H477.

Native local integration (2026-10-09): completed command, memory-neighbor, advisory,
generated-image and selected-image candidates are combined with voice orb, dictation and
briefing controls. Mobile284/native137, TypeScript and Android/iOS exports pass;
mode transitions fence old dictation and image reviews. Camera permission remains absent,
while the selected-photo plugin preserves the explicit dictation microphone permission.
This does not modify browser/backend behavior or close device/live-Hub acceptance.
See mobile/docs/mobile-integration-20261009.md.

HUD text contrast (local candidate, 2026-10-09): secondary text moves from the
decorative `--ink-3` token to the existing readable `--ink-2` foreground across
CSS and inline text, including status/consent labels and SVG text. Icon-only,
stroke and background uses retain their decorative colour. Browser measurement
and remaining exclusions are recorded in `docs/hud-muted-text-contrast-20261009.md`;
this is not a claim of complete WCAG conformance or native-device parity.

H277 recovery (2026-10-08): the active chat, floating chat and cockpit image composers now review the actual selected local Ollama agent/model/session. Reviewable prior image handles are bounded to that session and cleared on restart/reload. A selected turn with an unresolved conversation ID stays disabled; changing topic or agent invalidates pending work. Owner-only selected prepare/send/history routes preserve legacy standalone VLM behavior. H18.31 now has a local native candidate for bounded photo-library snapshots, exact selected model/session review, explicit send and process-local active-history choices. It records ambiguous delivery before dispatch and requires explicit History inspection before retry; no browser or backend behavior changed. Device/live-Hub acceptance remains open. See mobile/docs/h1831-selected-images.md.

H078 recovery (2026-10-08): existing Admin Settings exposes commands.quick_commands as an initially empty JSON map. Owner /help lists valid aliases and fixed commands. Execution queues through existing approval tasks and terminal gates; no new command editor or argument templates are added. Native H18.26 catalog code is locally implemented; device/live-Hub acceptance remains open.

H063 recovery (2026-10-08): typed /new, /reset and /undo are owner commands. Chat follows the concrete ID returned by /chat or the SSE end event; Sessions reopens the exact selected transcript, and desktop synchronization keeps the selected topic. Admin exposes reset policy, channel/type overrides and stall settings. Old transcripts are retained; empty sessions restart correctly and malformed snapshots fail closed. H18.30 local continuation adds native mobile ID transitions, scoped restart persistence and stale-response fences; device/live-Hub acceptance remains open. Direct web/CLI automatic reset/stall observation remains open.

H595/H660 recovery (2026-10-08): existing Admin settings now expose the execute-code opt-in, persistent-session setting, digest-pinned session image, project/strict mode, project directory and allowed environment names. Existing sandbox status/reset remains the operator surface. Complete project context is projected read-only; unconfirmed one-shot Docker teardown retains its snapshot and reports uncertainty. Native mobile configuration and live Windows Docker acceptance remain open.

Hermes runtime (2026-10-06, PR #1233): Admin now has private runtime start/stop,
session/RPC/event controls and exact queued-action approve/deny controls. The
operator CLI uses the same authenticated API. This is intentionally owner desktop
administration. Upstream REST/PTY/SPA and native-device acceptance remain outside
this controlled headless surface; see `docs/hermes/OPERATOR.md`.

H063 (2026-10-05): channel reset/index/stall policies run on the host through
existing settings and channel ingress. No dedicated lifecycle configuration panel
was added. HUD/API chat paths retain their current lifecycle; gateway validation
does not claim new browser or native controls, live adapter acceptance, or mobile
device verification.

H227 inspector (2026-10-04): the existing Inspector panel now shows the resolved
model/route and distinguishes unresolved base, legacy and withheld previews.
Refresh replaces stale route/prompt details. Its estimate is a fixed empty-turn
preview; history, user input, tool schemas and active cache state are omitted.

H075/H581 Kanban (2026-10-05, partial): the pinned durable SQLite state and local
tool handlers are registered behind `llm.kanban` (default off) in the existing
owner ToolRPC/chat path. The adapted Hermes CLI is available as `nerva kanban`
and the typed owner `/kanban` command. The 46 donor HTTP method/path pairs and
command endpoint are mounted under `/api/kanban` with admin authentication;
the separate event WebSocket checks host, origin, current admin authority and
board scope. CLI/API board selection is shared and persistent. ProjectsMode now
mounts a Kanban board and task drawer. The panel reads scoped board, project,
profile and orchestration data; supports board/task CRUD, bulk task changes,
comments, local attachment upload/download and an explicit dispatch request;
it refreshes on the authenticated board event WebSocket, reconnects and polls.
There is no tenant configuration UI yet.
Approved worker intake is available through the existing admin API
and coordinator with a separate default-off dispatch flag; approvals use the
existing inbox. The coordinator runs approved workers concurrently within total
and per-agent caps. Explicit owner chat dispatch uses the same signed queue;
the ordinary inbound model-tool restriction is unchanged.
Advanced worker controls remain required Hermes work. Owner project CRUD is now
reachable through `nerva project`, typed `/project` and its authenticated command
transport; the project inventory reads the real scoped store. Workspace proposals
bind board/project/owner roots before approval, and registered file reads and
project conventions use the claimed worker's isolated workspace. Registered file
mutations and local-host terminal commands now create independent signed child
approvals and atomically park the parent as `needs_input`. Execution opens a fresh
scope at the persisted cwd, checks the exact source run and directory identity,
and refuses revoked roots or board inputs. Cleanup preserves active child approvals.
Automatic governed resume, crash reconciliation of incomplete intake, scoped remote
terminal targets and goal judging remain unfinished integration. URL attachments now propose
separate signed egress approvals behind `llm.kanban_network_attachments`; each
redirect requires another approval. The chat tool uses the existing Decision
Inbox. The drawer handles local files; URL attachment review and advanced
worker/recovery actions are still missing from it. Profile editing,
orchestration settings, model selection, run inspection/termination and native
board/worker controls remain open. This is not full Hermes parity.

Kanban client route gaps: the following server contracts still need their
HUD consumers. Native Kanban controls remain open even for the routes consumed
by the browser. Host CLI/chat and API bindings above are local progress;
registered but unbound effects retain explicit failures until their adapters land.

- `/api/kanban/assignees`
- `/api/kanban/boards/import`
- `/api/kanban/boards/{slug}/export`
- `/api/kanban/boards/{slug}/switch`
- `/api/kanban/config`
- `/api/kanban/diagnostics`
- `/api/kanban/estimate`
- `/api/kanban/home-channels`
- `/api/kanban/links`
- `/api/kanban/model-options`
- `/api/kanban/profiles/{profile_name}`
- `/api/kanban/profiles/{profile_name}/describe-auto`
- `/api/kanban/runs/{run_id}`
- `/api/kanban/runs/{run_id}/inspect`
- `/api/kanban/runs/{run_id}/terminate`
- `/api/kanban/stats`
- `/api/kanban/tasks/{task_id}/decompose`
- `/api/kanban/tasks/{task_id}/estimate`
- `/api/kanban/tasks/{task_id}/home-subscribe/{platform}`
- `/api/kanban/tasks/{task_id}/reassign`
- `/api/kanban/tasks/{task_id}/reclaim`
- `/api/kanban/tasks/{task_id}/specify`
- `/api/kanban/workers/active`


H011 checkpoints (2026-10-04): authenticated owner status/list and exact
maintenance previews now use typed `/checkpoints` and bare `/rollback` through
the existing chat routes; the host CLI uses the same owner notice contract.
These commands do not enter backend conversation history or attached context.
Owner typed commands and host CLI now support diff, selected/force restore and
index maintenance. Effects require a signed current human task, the live kernel,
exact intent/root checks and the original session lease. Only complete file
restore commits the current-last-user conversation rewind; partial effects keep
undo and conversation history. Dedicated checkpoint controls, size/retention
settings and complete checkpoint-owned payload cleanup remain open. Shared blobs
are retained. No browser or native acceptance run is claimed.

H487 terminal consent (2026-10-04): Decision Inbox shows only server-projected
reviewed categories and current session/always/deny choices. Choices submit the
exact offer revision through the admin route; changed offers reload for review.
Session-only categories retain their bound even when always is chosen. Ordinary
once/edit/reject/defer remain. Native reusable controls, Telegram cards and all
other accepted consent producers remain open; terminal-only delivery is not
full H487 or live/device acceptance.

H277 (2026-09-27): Decision Inbox renders advisory risk scores, escaped rationale,
judge identity/locality and truncation/flag warnings. Pending opinions poll with
an independent wall-clock limit per task; decision controls remain available.
Role configuration is shown beside Model Fingerprints through authenticated
`/api/llm/roles`; a role settings editor remains open. Offline component tests cover
late results, refreshes, failed reads and browser-throttled timers; this is not a
claim of a live model or native mobile acceptance run.

H18.29 native candidate (2026-10-09): the existing Approvals cards now show the
optional advisory opinion and pending state, with manual pull-to-refresh. A separate
read-only model roles view names configuration and says connectivity has not been
checked. Automatic native polling is deferred; #1233 decision-lifecycle integration,
physical-device review and live hub/judge acceptance remain open.

H277 terminal guardian (2026-10-03): trusted owner opt-in can apply a signed
one-operation smart approval to terminal tasks. Decision Inbox distinguishes
guardian DENY/ESCALATE from advisory risk scores and preserves owner controls;
pending guardian reviews have their own label. Advisory defaults remain.
Native labels/configuration remain H18.29; no live-provider/device proof is claimed.

H277 video continuation (2026-10-02): the default-off `video_analyze` tool uses the
existing Decision Inbox approval surface. Security Posture has an independent
Video analysis consent row and independent Video fallback 1–4 controls for configured
candidates. A dedicated video picker/preview, an in-HUD role editor,
inbound video ingestion, and live native-video model acceptance remain open.
The optional primary transient retry and valid-empty full-chain retry use existing
task notices/results; there is no in-HUD editor for either environment setting.
Enabled empty recovery reports its consumer-call index separately from each
route's attempt index. A malformed or blocked result does not permit this restart.

H277 OpenRouter video (2026-10-04): primary, inherited vision and fallback routes
use the same Decision Inbox and role-consent controls. The request emits the
approved provider privacy block. An in-HUD video-role/preferences editor and
video picker remain open; offline verification does not prove live model support.

H277 local auxiliary models (2026-10-02): server-side title generation, recall
rewriting, conversation review, compression and governed acquisition capability/plan
generation can use independent local model IDs. Existing output surfaces are
unchanged. The six `JARVIS_AUX_*_MODEL` environment settings have no in-HUD editor
or configuration listing yet. Acquisition retains its existing governed routes. The server can retry five nonstreaming auxiliary calls after a typed LM Studio temperature rejection; the requested temperature is initial, and the repaired call uses the provider default. No new HUD control is needed or claimed.

- **Runtime verification.** Nothing was verified against a *running* backend (the build sandbox has
  no `fastapi`). Run `python serve.py` → open `/v2`, click **every mode + every Console (▦) panel**,
  and compare against `/` (v1) / known values. The **mock‑fallback** design hides wrong‑but‑not‑
  failing wiring (a bad field map shows seed data, not an error), so this pass is essential. File
  shape‑mismatch fixes as found.

## 1. Make real‑vs‑mock visible
- ~~Surface the loader's existing `live` flag as a **● LIVE / ○ SEED** indicator (top bar + per‑panel).~~
  ✅ **DONE (verified 2026-07-04):** mode-level `LiveSourceChip` plus per-panel `PanelChip`
  make LIVE/SEED visible, and `panel-chip-coverage.test.ts` pins every Console card.

## 2. Deepen the P4c Console panels (read/basic → full)
- ✅ **Chat-command discovery (HA-4i-catalog):** the Quickbar panel reads `GET /api/commands`
  from the live registry, with usage and owner markers filtered by chat's principal. Loading,
  empty and unavailable states are distinct. This is a catalog; commands execute through chat.
  Native H18.26 now has a locally implemented Chat catalog modal using the same endpoint and
  principal credentials. It shows command, usage, description and owner tier, distinguishes
  loading/empty/error/unavailable states, supports retry and inserts a choice into the composer.
  Native device/live-Hub acceptance remains open; actual Send follows the guarded chat session path.
- ✅ **Ambient Watch (H33.6):** the Home cluster now reads the redacted live ambient runtime,
  showing monitor/source health, last policy decision, rung counts, and the single global
  attention budget. Monitor administration remains in the separately authenticated admin API;
  event content, subjects, predicates, recipients, and delivery ids are never rendered.
- ✅ **Settings DB**: full inline editor (toggle/slider/select/text per key) saves through
  `PUT /api/admin/settings/{cat}` in `SettingsPanel`.
- ✅ **Prompt versions**: `PromptsPanel` has A/B, diff, rollback, edit, preview, and commit controls
  over `/api/admin/prompts/{id}/*`.
- ✅ **Data Spaces**: list/create/delete plus assign/unassign controls are live in `DataSpacesPanel`
  over `/api/memory/spaces` and `/api/memory/spaces/{assign,unassign}`.
- ✅ **Secrets / Capabilities**: the secret store form is live in `SecretsPanel`, and
  `CapabilitiesPanel` can issue tokens, keep recent grants visible, and check a
  token/capability pair through `GET /api/security/capabilities/check`.
- ✅ **Capability Registry**: `ReadinessPanel` reads canonical `GET /api/capabilities` and
  shows readiness, risk, supports, and confidence without fabricating verification.
- ✅ **Rooms**: create + send with `@mentions` are live in `RoomsPanel`, and the selected-room
  history drawer reads `GET /api/rooms/{id}/history`.

## 3. Per‑mode live‑wiring depth
`api/live.ts` wires the headline data for Memory / Observe / Interop / Autonomy / Trust / Admin.
PR #505 adds base LIVE/SEED gates for Build / Comms / Finance / Health / Knowledge / Family,
with plugin-configured checks instead of seeded success. Still open:
- **Build**: base live wiring reads workflow DAG + skills marketplace + sandbox from
  `/api/workflows`, `/api/skills/marketplace`, and `/sandbox/status`. Create/edit is closed
  (DRA-28): the Console's `WORKFLOW BUILDER` panel replaces the read-only step generator —
  generate a step, append it to a draft, and save through `POST /api/workflows` /
  `PUT /api/workflows/{id}` (admin), with the 422/401 refusal rendered inline. The steps
  textarea stays the editor of record for the advanced `router`/`critic`/`loop`/`subflow`
  configs; a graphical DAG canvas for v2 was **dropped by owner decision 2026-09-01** (BUG-2b.2):
  the JSON-paste `WORKFLOW BUILDER` panel is the v2 editing surface of record; the legacy v1 HUD's
  `WorkflowCanvas` (`agents/web/static/workflows.js`) does exist and retires together with the v1
  HUD (§8 / AUD-15) — ported only on demonstrated demand, as a fresh spec with its own id.
- **Memory**: DW-1 replaces the live mode's sample graph with read-only entity search,
  selection and connected-entity navigation over `GET /api/kg/entities` and
  `GET /api/kg/entities/{name}`. Reads use current user credentials, a ten-second deadline,
  a one-MiB response bound and 100 displayed entities/relationships; cancelled or superseded
  reads cannot replace the current selection. Empty/unavailable data stays explicit. Recalls
  use real search results with no sample fallback, and headline statistics remain unchanged.
  The sample graph, recalls, topic freshness bars and historical slider appear only in explicit
  Demo. Live decay ranking and bitemporal as-of navigation remain open. Relationships are
  presented without directional or semantic-distance claims; this is no 3D embedding map.
  Native H18.28 has local Graph navigation and stale-read guards over the same KG routes;
  focused native/API tests pass, while device/live-Hub acceptance and integration remain open.
  React Native verifies the one-MiB response bound after `Response.text()` on transports
  without a reliable stream reader, and rejects an oversized `Content-Length` before reading.
- **Trust**: real `%‑local` meter (needs a locality/cost summary endpoint, §6).
- **Autonomy**: per‑agent AUTO/ASK/OFF **policies** (settings‑backed).
- **Comms**: rooms + registered **Discord/Slack** channel status now feed the mode. The Console now
  has a Safe Comms draft surface over `GET/POST /api/integrations/social`, so X post/reply/DM drafts
  enter the existing approval queue/preview path instead of sending directly. #551 adds
  channel inbox transport v0 for telegram/web: inbound threads persist through
  `GET /api/channels/inbox*`, live rows show a governed reply composer, and replies queue through
  `POST /api/channels/inbox/{thread_id}/reply` before approved sends use the live channel manager.
  Email/WhatsApp inbox transport remains deferred until their live send seams are proven.
- **Finance / Health / Knowledge / Family**: base mode switching is plugin-gated. Finance reads saved
  watchlist/payments and keeps `balance` mock payloads as SEED; Health waits for the Apple Health LAN
  bridge; Knowledge waits for configured websearch backend; Family waits for WhatsApp bridge/frigga
  live data.
- **Dossier**: wire to `/api/agents/{id}/soul` + `/memory/{id}` + run history `/api/agents/{id}/history`
  (currently reads the `DOSSIER` mock).

## 4. Cockpit / signature interactions
H18.24 native continuation (2026-10-09): a local SVG orb candidate in Chat follows
actual TTS playback events, labels preparation separately, and cancels late playback
after stop or a hub change. Reduced motion and background state pause animation.
Native Chat now has a local explicit dictation candidate: bounded capture, fresh
mic trust and permission checks, stopping state, and local STT draft insertion.
The H18.25 local wall candidate now adds a bounded SVG tier field, source-backed
stat cards and chips, and a default-hidden spoken line in Chat. It preserves
unknown-source semantics and cancels background/scope-stale updates. Physical
device/live STT acceptance remains open. The separate source-card candidate adds
returned approvals, a calendar sample, local-model/voice reports and heartbeat
schedule counts, with unknown data kept explicit and private details discarded;
see `mobile/docs/h1825-briefing-wall.md` and `mobile/docs/h1825-briefing-sources.md`.

- ~~**Network task‑fan**: v2 `NetworkBrain` doesn't render per‑agent task dots from `/tasks` (v1 did) —
  the old task fan exists in `network.tsx`, but the current cockpit renders `NeuralMesh`; integrate
  live `/tasks` dots into the current mesh or retire the stale `NetworkBrain`.~~
  ✅ **DONE (2026-07-04, #521):** `app.tsx` passes the existing live `/tasks` state into
  `NeuralMesh`, which renders honest task spokes/dots plus a visible task count; empty or
  unknown-owner queues render no invented fan.
- ~~**Per‑message TTS** (🔊 → `/tts`) + **browser mic / SpeechRecognition** input + voice auto‑speak.~~
  ✅ **DONE (verified 2026-07-04):** `cockpit.tsx` renders per-message replay via `playTts`,
  `InputBar` toggles the `useVoice` loop, and `app.tsx` wires mic → local STT → turn → speak.
- ~~**Sentence-level TTS streaming** (H5.16)~~ ✅ **DONE (verified 2026‑07‑02)** — `voice.ts`
  `speak()` tries `streamTts` first (framed chunks played back-to-back, `voice.ts:206`) and falls
  back to whole-reply `/tts` on 409 when the server opt-in is off. *Remaining H5.16 tail lives in
  BACKLOG (synthesize mid-stream; browser wake-word).*
- ~~**Streaming cognition**: upgrade to a real SSE stream.~~ ✅ **DONE (verified 2026-07-04):**
  `app.tsx` subscribes to `/api/cognition/stream` and maps cognition frames into the cockpit trace.
- ~~**Strict-local / mic trust badge** (H12.10).~~ ✅ **DONE (verified
  2026-07-04):** `shell.tsx` renders strict-local and mic-muted badges from the live trust payload.

## 5. Settings / preferences UI
- ~~The design‑only `TweaksPanel` was dropped. Accent + language persist (palette toggles), but
  **look / density / motion / scanline / dotgrid** aren't user‑changeable in‑app (defaults only) —
  add a small settings menu (or a gated tweaks panel) that changes + persists them.~~
  ✅ **DONE (2026-07-04, #523):** the command palette now exposes look, density
  (compact/normal/comfy), motion (lively/calm), scanline, and dotgrid controls; all are
  client-side HUD preferences persisted by `App`.

## 6. Toolchain / CI hardening
- ~~**CI frontend‑build + stale‑bundle guard**~~ ✅ **EXISTS** — the `hud-v2-build` job in
  `.github/workflows/ci.yml` runs `npm ci` → `tsc --noEmit` → vitest → `vite build` and fails
  if the committed `agents/web/v2` differs from a fresh build. *(This line was stale — noticed
  2026‑06‑10 while re‑checking the punch‑list.)*
- ~~**OpenAPI types**~~ ✅ **DONE 2026-07-03** — `frontend/src/api/schema.gen.ts` is generated from
  the live FastAPI `/openapi.json` via pinned `openapi-typescript`; CI boots the backend,
  regenerates, and fails on a schema diff. Consumer migration remains gradual by design.
- ~~**Self‑host fonts**~~ ✅ **DONE (2026-07-04, #525):** HUD v2 now vendors
  local Latin-variable WOFF2 assets for Space Grotesk + JetBrains Mono and loads them
  through `@font-face` in `frontend/src/styles.css`; runtime font-network dependency is removed.
- **ESM cleanup**: the ported prototype files keep an `import { … } from './ui'` barrel + loose types;
  tighten to real per‑module imports + TS types over time.

## 7. Backend additions (from the plan §6)
- ~~`GET /api/cognition/stream` (SSE)~~ ✅ **DONE** and consumed by the cockpit. Provenance on the
  chat stream is already surfaced via the existing provenance chip/modal.
- ~~`GET /api/analytics/locality`~~ ✅ **DONE 2026‑06‑10** — computes %‑local from the run‑history route field; HUD Trust meter prefers it, falls back to strict‑local proof, never fabricates a split (`local_pct` null until real routed runs exist).
- Howard ingestion API — only if we ever surface the digital twin (currently `NOT_IN_HUD`).
- ~~Emergency-stop control~~ ✅ **DONE 2026-08-29** (2026‑08‑28, hermes v2026.8.27 port): Admin
  mode now carries the "AUTONOMY PAUSE (ESTOP)" card over `GET /api/ops/estop` +
  `POST /api/ops/estop/{engage,resume}` — two-step confirm with optional reason, engaged
  reason/timestamp shown, single-click resume; typed wrappers in `frontend/src/api/actions.ts`,
  the three routes removed from the parity punch list. Named distinctly from the Trust
  kill-switch ("EMERGENCY STOP · halt all agents"), since estop only pauses NEW autonomous work.

## 8. Cutover (P6 follow‑through)
- Once verified, flip the default: `JARVIS_HUD=v2` (or hardcode) so `/` serves v2; keep `/v1` as the
  escape hatch; then archive the old `agents/web/` HUD and update `README` / `STATUS.md` / `NERVA.md`.

## 9. Known infra issue — ✅ resolved (2026‑08‑31)
- The old note here said CI **`Analyze (python)` (CodeQL)** intermittently failed because code
  scanning was unavailable on a private repo. That is overtaken: the repo is public, code scanning
  is enabled, and the analyze step uploads SARIF successfully (run 33384718270 logs *"Analysis
  upload status is complete."*). Settled posture: **CodeQL = advisory, push‑to‑main + weekly, not a
  required check, fails loudly on analysis/upload errors** (`continue-on-error` removed
  2026‑08‑31). The only remaining action is owner‑side — drop `Analyze (python)` / `CodeQL` from
  required status checks and delete the code‑scanning merge‑protection ruleset
  ([`OWNER_TASKS.md`](../OWNER_TASKS.md) §GitHub settings).

## 10. Parity re‑audit — 2026‑06‑10 (backend moved ahead again)

H022 host dependency audit (local, 2026-11-04): `nerva security [audit]` inventories
the invoking host, then uses admin `POST /api/security/dependencies/audit` for
kernel-mediated OSV lookup. This CLI contract intentionally has no HUD/native
inventory panel: those clients run in different environments. Offline, skipped
and incomplete coverage are reported separately from a completed audit. The
endpoint is classified as machine-facing in the parity gate; no live OSV or native
acceptance follows from the repository's synthetic transport tests.

The 2026‑06‑09 backend waves (PR #178/#180) shipped new surfaces **with no HUD controls**, on top of
the still‑open depth items above. Snapshot: backend ≈299 routes; HUD v2 actively calls ~50, partially
~10; **~37 write/recent endpoints lack any UI control**. New since the 2026‑06‑05 plan:

- `GET /api/cognition/stream` (SSE, NTH‑1 ✅ backend) — ✅ consumed by the cockpit trace.
- Sender pairing gate (H12.19, 4 routes) — not in Comms.
- Cloud auth‑profile rotation (H12.20, `GET /api/llm/auth-profiles`) — not in Admin.
- Transcript → governed tasks (H12.25, `POST /api/transcripts/ingest`) — no surface.
- A2A approval inbox (H16.2 `/api/a2a/inbox*`), payments lifecycle actions (H16.3
  approve/reject/settle), marketplace review (H12.12) — read‑only or absent in Trust/Build.
- Still missing interactive controls (carried from §2–§5): preference-learning suggestions.

**Conclusion:** coverage gate still green (nothing silently dropped), but the *depth* gap regrew.
Tracked as **TASK‑2** in `BACKLOG.md`; estimated 3–5 PRs (~2–3 weeks part‑time) to "nothing missed".

### 2026‑06‑10 depth pass (same day, PR #181) — the control gap is CLOSED

All ~37 missing **write/recent controls** above now have live HUD surfaces (Console panels in
`frontend/src/gap.tsx` + Trust mode + cockpit):
cognition SSE stream (cockpit live trace) · payments approve/reject/settle (Trust) · sender
pairing approve/reject/block + code (H12.19) · injection scan (H17.1) · transcript→tasks ingest
(H12.25) · escalation targets+send (H12.11) · reflection status+run · heartbeat run/start/stop ·
bench promotion (`/learning/promote`) · marketplace review ✓/✕ (H12.12) · eval runs + compare ·
AI step builder (H10.7) · sandbox execute (DEV_MODE‑gated, honest 403) · agent templates
(H10.29) · LM Studio server/load/unload · cloud auth profiles (H12.20). Admin‑guarded calls now
send the admin token (`actA`). +7 frontend tests (19 total).

**Still open (the tail of TASK‑2, re‑verified 2026‑07‑05):** O26-P3.1 closes the §3 plugin-gated
base wiring in #505 (Build/Comms/Finance/Health/Knowledge/Family), and the Safe Comms draft panel (#527)
closes the draft-before-send UI over existing governed social actions. #551 adds
channel inbox transport v0 for telegram/web. Remaining:
owner live-data/plugin setup (bank/broker/quotes, Apple Health bridge, websearch backend, WhatsApp
bridge/frigga live data) and non-v0 inbox channels.
Estimated 1–2 PRs after #505 for owner-gated/plugin work.
*Since‑closed items previously listed here:* CI stale‑bundle guard ✅ (`hud-v2-build` in `ci.yml`),
§7 locality endpoint ✅ (`GET /api/analytics/locality`, consumed in `app.tsx`/`shell.tsx`), and the
BUG‑17 audit‑verify Trust chip ✅ (`modes.tsx:117-165` renders the live
`GET /api/security/audit/verify` verdict), the 0.39 saved‑watchlist `WatchlistPanel` ✅, and
per-panel LIVE/SEED chips ✅ (58/58 Console cards declare a `PanelChip` signal). Data Spaces
assign/unassign controls ✅. Rooms selected-history drawer ✅. Capability issue/check UI ✅.
Current-mesh task fan ✅. Preferences/tweaks UI ✅. Self-hosted fonts ✅. Safe Comms draft UI ✅ (#527).
Safe Comms channel inbox transport v0 ✅ (#551).
O26-P3.2 adds a Vitest reconciliation guard so this document cannot re-list shipped
TTS/mic/cognition/trust or Console controls as missing.

**O29 Media Director (2026-07-13):** the default-off `/api/media/*` device, session, present,
and restore surface is live in the Console Build cluster. `MediaDirectorPanel` separates the
read board, explicit user presentation/restore controls, and admin-authenticated registry
controls; queued approval, kernel refusal, nested `output.ok=false`, and driver-verified success
are rendered as distinct outcomes. The panel displays bounded metadata only and never embeds
remote media. `tests/test_hud_v2_parity.py` pins every Director route to the live Build surface.

**H30.5 House Brain (2026-07-13):** the default-off `/api/house/*` surface is live in the new
Console Home cluster. `HousePanel` renders bounded topology and pseudonymous presence, pauses
controls whenever live Home Assistant state is unavailable, and exposes only narrow governed
light/climate/security proposals. Security proposals remain visually distinct and use an
admin-authenticated two-step challenge bound to the durable task; success is never shown for a
queued, denied, or unverified outcome. Native mobile parity is read-first with an Approvals handoff
and intentionally has no security confirmation shortcut. The HUD parity gate pins every user route
to the Home surface.

**H31.5 Camera Intelligence (2026-07-13):** the default-off `/api/cameras/*` surface is live in
the Home cluster. `CameraPanel` shows only bounded time/type/camera/zone/confidence metadata and
optional strict-local description provenance, with deterministic temporal search. It creates no
image/video/embed or private media request. Admin-authenticated ONVIF discovery is onboarding-only and
needs the manually installed `wsdiscovery` package (deliberately unlocked; a stock install's
discover route answers `onvif_dependency_missing` with the install remedy in `detail`);
native parity covers status, recent events, and private-body search without an admin shortcut.

**H32.6 Capability Acquisition (2026-07-13):** the default-off `/api/acquisition/*` surface is
live in the Build cluster. `AcquisitionPanel` separates user-readable lifecycle/reuse/package and
hash-only audit state from the admin-authenticated revoke, rollback, export, and exact-confirmation
purge controls. It never renders request goals, source extracts, receipt bodies, package paths, or
full correlation hashes. Native parity is deliberately read-only over the same bounded user APIs.

**H28.4 Operator depth (completed 2026-07-14):** Console → Build now hosts a dedicated
`OperatorPanel` over the four existing browser check/plan-preview and desktop preview/run routes;
no route or governance bypass was added. Browser policy and plan checks are dry-run only and expose
no Run control. Desktop submission is preview-first: editing invalidates the preview, and submit
uses the deep-cloned canonical snapshot. The result reducer distinguishes proposed, queued,
blocked, failed, partial, and executed outcomes, with an explicit warning against whole-plan retry
after partial execution. Native mobile hides `toolrpc.desktop_run` payloads and omits Approve while
retaining Reject/Defer. Evidence: `operator-contract.test.ts`, `operator-panel.test.tsx`,
`gap-panels.test.tsx`, `approvalsDesktopBoundary.test.ts`, and the strengthened
`tests/test_hud_v2_parity.py` caller gate.

**H34.1 Mission Control (2026-07-24):** the swarm cockpit ships as a **standalone
brain.html-pattern page** at `/mission-control` (self-contained dark HUD; polls the new read-only
`GET /api/swarm/summary`; steering reuses the existing governed autonomy/missions/A2A endpoints
with the shared `hud.admin_token`). Both routes are mapped to `observe` in the parity RULES.

**H34.4 SwarmPanel (2026-08-10, done):** a React `SwarmPanel` inside Console → Observe reads the
same `GET /api/swarm/summary` feed read-only — kernel halt/armed status, the autonomy funnel,
workspace counts (missions/workflow runs/sub-agents), the A2A inbox when enabled, and which
dev-swarm agent (`claude`/`codex`/`opencode`/`antigravity`) currently holds a `lock.py` lock — then
links out to the standalone `/mission-control` page for the full HITL controls. Zero new backend
route; the cockpit is now one keystroke from chat, and the standalone page stays either way.

---
**HA-4i local images (2026-09-09):** the optional ComfyUI backend is reachable through
the governed `image_generate` proposal and existing approval queue. **Composer and selected
result view delivered:** Console → Build → Images shows configuration as untested, proposes
the exact prompt, hands approval to the existing Inbox and observes one exact task through
an admin-only state projection. Only a validated successful artifact is fetched as bounded,
authenticated PNG bytes for a revocable browser preview/download. Lost POST responses remain
uncertain with no automatic retry. Reopening/hard refresh clears panel state; entering the
known task ID resumes observation without resubmission. A persistent gallery, owner-host
ComfyUI proof and native presentation (H18.27) remain open. The production approval
bridge supports `off` and `enforce`; `hold` intentionally refuses execution.
Per-conversation access isolation is not added by this surface.

H18.27 native continuation (2026-10-09): a local Media-screen candidate adds
configuration-only local status, exact-prompt proposals through the existing approval
queue, task restoration across the approval handoff, manual status refresh and
authenticated PNG preview/save. It does not initiate cloud generation or repeat a
proposal automatically. Real-device/live-generator acceptance stays open. The server
projects three exact, normally completed cloud provider-response failures, five
typed local OpenAI-compatible response failures and the documented ComfyUI history
error shape as `failed`. Local adapters persist fixed producer markers; legacy
rows without them stay uncertain. The ComfyUI marker requires the matching prompt
history with exact error/false status fields; malformed or incomplete history is
not enough. Verified cloud artifact recovery keeps precedence. Web/native readers
state that no usable image was verified and add no preview or automatic proposal.
Generic failures, malformed results, ambiguous delivery and withheld output remain
`uncertain`; native cloud proposal controls are unchanged. See
[cloud evidence](../project-image-provider-failure-20261009.md),
[typed local evidence](../project-local-image-response-20261009.md) and
[ComfyUI history evidence](../project-comfyui-response-20261009.md).

**HA-4i extension inspection (local V44/V46/V47, 2026-11-13):**
Console → Build → Extensions now reads user-guarded `GET /api/plugins/extensions`.
It separates declared and currently callable tools/commands, required arguments,
observation events, signature verification and approval. Disabled/uncomposed/error
states remain explicit; failed refreshes hide previous metadata. Mobile Status has an
opt-in equivalent. Neither view activates code or grants consent. Offline tests and
build checks cover these surfaces; live browser/device acceptance remains unverified.
Native third-party UI injection remains excluded. See `docs/EXTENSIONS.md` and the
cumulative local continuation checkpoint for exact executed evidence.

*Parity gate (`tests/test_hud_v2_parity.py`) tracks all routes → every one is mapped to a v2
surface or `NOT_IN_HUD`, so nothing above can silently disappear — these items are about depth, not
coverage.*


<!-- models-context-2026-09-15 -->
Model/session context: backend clock and request shaping apply across channels. Existing /admin metadata exposes compatible provider/model, explicit cache/effort capability toggles, per-model vocabularies and Ollama num_ctx. Dedicated mobile/HUD model controls remain a UI gap; no new routes or mobile controls are claimed.

### H178 native floating chat — 2026-09-15

Desktop-only: Tauri tray/main controls open a frameless chat using the existing HUD
conversation and authentication; geometry recovery and handoff are implemented.
Mobile retains its normal chat. macOS host validation covers the bounded window
surface; Windows/Linux, compositor-exclusive overlays, transparency/frost, click-through,
global shortcuts, move-to-pointer and underlying-window capture remain unverified or unimplemented.
See `desktop/README.md`; full Hermes H178 remains partial.

### 2026-09-15 — scheduled automation depth (H146/H449)
Jobs now wires all admin diagnostics/tick/notepad routes and adds a sixteen-card typed
blueprint gallery, custom four-action builder, full action/options editing and visual schedules.
Per-job repeat counts attempts, including failures; manual runs cannot exceed the bound.
Explicit configured channel names retain owner destinations and existing delivery gates.
Remaining: isolated per-job provider/model/workdir/toolsets/skills, cross-profile listing and
real scheduler/channel proof. Tick uses the active application timezone (including DST) and refuses to compete with a live scheduler.

H146 followup: the topbar Automations entry now opens a roomy dedicated Jobs workspace;
Console integration remains. Custom creation uses a native modal with initial focus,
Tab containment, Escape/cancel and focus restoration. Browser proof uses mocked job reads;
no live channel was enabled. Generated OpenAPI types now include all four added job routes.

2026-09-15 — H12.26: Artifacts now includes default-off binary upload, authenticated
preview/download, pin/delete and honest errors. Supported magic-sniffed image,
audio, video and PDF only; active formats and office documents remain refused.

2026-09-15 — H515/H518: Images exposes configured local backend/checkpoint selection, up to four blended references and explicit 2× bicubic upscale. Media Gallery searches and downloads supported catalog/cache/attached files through authenticated object URLs and exports visible supported rows to ZIP. Runtime ComfyUI proof remains unperformed.

2026-09-27 — H517 local provider slice: Images reads per-backend protocol/model
and edit/upscale capabilities. A configured `openai_images` service can generate
through the same Inbox/worker/artifact path; switching from ComfyUI clears
incompatible edit/upscale fields. Default-backend models no longer assume ComfyUI.
See [configuration and limits](../hermes/local-image-providers.md). Arbitrary
adapters, other media registries, live service proof and native controls remain open.

2026-09-15 — H684: Jobs doctor displays the additive structured health report through the existing diagnostic control. Backend and CLI detect scheduler stalls and stored failures. Script/no_agent/workdir options and production-host proof remain open.

H129 (2026-09-15): all 18 existing HUD modes and 113 console panels have explicit URLs, history, titles and lazy loading, with selected-panel focus and mobile navigation. Profile/plugin routing remains outside the implemented single-owner route registry. Browser smoke is local and backend-stubbed.

### 2026-09-27 — H487/H513 integration

Decision Inbox supports bounded human reasons, verified owner-submission group cards,
one-use approval with follower promotion, and atomic group rejection. Legacy Actions
provides the same grouping controls for action requests. Model-originated and browser
requests without a trusted grouping context remain separate; full H487 is partial.

Security Posture shows declared provider policy, warnings that persist after consent,
and allow/revoke controls bound to the configuration displayed. Unavailable or
ambiguous consent cannot be granted. Routed agent/tool-loop/cache dispatch rechecks
consent; independent direct provider clients are outside this increment.

The approval judge now has its own consent row and allow/revoke controls. Provider
and role setting failures disable their respective controls independently. The role
acknowledgment never enables remote judging and never inherits a provider grant.

Governed image empty recovery (H277, 2026-10-02) discloses its optional one-call
retry budget in the composer before remote acknowledgment, and beside policy notes
in local describe/screen panels. Refreshing a changed binding clears the previous
acknowledgment. The environment setting has no HUD editor; native mobile rendering
and live model acceptance remain open.
Native image/video normalization now supplies visible text first, then typed
reasoning fallback through the existing answer surfaces. This requires no new HUD
control or schema; provider errors/malformed mixed output remain failures rather
than displayed model answers. Browser/device acceptance is separate.

Composer image status and successful results now retain a visible data-policy
warning. The existing per-destination remote checkbox remains request-scoped;
provider/judge consent cannot replace it. No unattended vision grant was added.

Decision Inbox displays an explicit approval deadline when the owner task API
supplies one. A missing or unreadable field preserves legacy cards. Approval stays
single-use, with the backend deciding whether the deadline has passed; the UI adds
no client-side authority or automatic approval. There is no general task creation
form in this panel, so deadline authoring remains the existing owner task API.

The independent VLM Describe and Screen Reflex panels show declared policy notes
and retain response warnings. Both align with strict loopback inference on the
Nerva server; the legacy describe remote checkbox is removed. Failed or empty
inference does not render as a successful description. These interactive routes
now have scoped dispatch checks; the standalone screen-locator has no verified production caller.

Trust now includes a separate Telegram image-description role, with local-server
requirements and independent configuration-bound acknowledgment/revocation. Unknown
role IDs have no controls. Judge/provider compatibility and unavailable-store
feedback are retained.

Trust now includes independent camera-description model-data controls as well.
The UI separates them from household camera consent, capture enablement and remote
access. Camera provisioning is still a separate H31 integration requirement.

2026-09-27 — Voice → Command providers now works with task mediation set to
`enforce`, using the existing Decision Inbox card and human approval. `hold`
continues to refuse registration. No new provider picker is delivered by this
backend prerequisite: multiple named speech providers and the shared media
registry remain open under H517/H613.

2026-09-27 — The subsequent named-provider slice adds independent TTS/STT rows,
registration/update requests, per-name clear (including pending-only requests),
explicit STT selection and exact name/revision on Inbox cards. Missing saved
selections remain visible as unavailable. Image and speech dispatch now use the
common registry. Full vendor/plugin/setup breadth remains open under H517/H613;
native mobile provider configuration is still a gap.

Task 10A/10B (2026-10-28/29) provides owner-only encrypted credential management
at GET/PUT/DELETE `/api/admin/llm/provider-credentials`, and explicit signed-model
selection at GET/PUT/DELETE `/api/admin/llm/provider-selection`. Responses expose
only configuration, revision and generation metadata. The selected runtime now
covers all six declared cloud dialects through guarded DNS/IP/Host/SNI sends and
body-lifetime mutation fences, with local synthetic owner/Kernel/Vault evidence.
HUD package review, key entry, risk acknowledgements, select/status/clear and
lifecycle controls remain open. A package-status `selects_model: false` means that
installation itself makes no selection; read the separate selection API for the
current binding. No live provider, billing, Docker or native-device readiness is
claimed by these API controls. H361 remains partial.

H512 authentication audit continuation (2026-10-09): the existing admin audit reader
shows typed HTTP guard and managed token lifecycle events through `GET /api/admin/audit`.
No new route or dashboard control is added. The native audit reader remains open
in `mobile/PARITY.md`; native bearer requests are covered by the shared server guards.
The broader login/session/WebSocket/native-auth event contract remains incomplete.

H161/H328 closure (2026-10-10): the existing pressure banner receives the same
response shape, with recovery now confirmed per volume even when another probe
fails. Existing skill offers recognize the native Kanban and other supported
toolset members. No new HUD control or route is needed; native pressure-banner
and dismissal presentation remains a mobile gap.

H450 closure (2026-10-10): schedule preview, job creation/editing, cron triggers,
status and fallback tick share the runner's active application timezone. Saving
a new timezone applies to running jobs after restart; absolute one-shot instants
stay unchanged. The existing Jobs workspace uses the corrected preview route.
Native job administration remains open in `mobile/PARITY.md`.

H512 MCP token continuation (2026-10-10): successful `/api/mcp/token` signing adds
a `token_issued` row with literal `surface=mcp` to that same admin audit reader.
The admin authorization row remains separate; minted credential tier is `user`.
No endpoint or UI control changes. The native audit reader and broader H512 event
coverage remain open, and the bounded audit queue still permits dropped events.

DRA-59 local observability (2026-10-09): Autonomy Control now reads admin-only
`GET /autonomy/mediation` and displays the effective queue mode separately from
evidence validity. Only verified recorded event counts are shown; unavailable,
malformed and refreshing states hide numbers. The section has no enable, approval
or raw-event control. B7 operational acceptance and broader task coverage remain
open. H18.32 now provides the local native Status counterpart with strict snapshot
validation and connection/read-order fences; physical-device/live-hub acceptance
remains open in [native evidence](../../mobile/docs/h1832-task-mediation-status.md).

### H686 current-turn duration — 2026-10-09 local candidate

Cockpit and focus chat share a duration strip from the optional `outcome.latency_ms`
on the current SSE end. The measured interval is the public orchestrator invocation,
including cleanup; it is not network round-trip time or model-only generation time.
A normally returned command or refusal may have a duration. Errors, cancellation and
uninstrumented turns have none. Selection is applied by the backend from the ordinary
Admin Settings `display.status_bar_fields` list (default `latency`; empty hides it).
The strip clears on new work or session/agent/demo changes and is not transcript history.
TPS and the complete H686 model/context/cache/compression vocabulary remain open;
Task33 extends the same outcome after its own review. H396 now supplies the whole-turn
completion/accounting fields described below. H18.33 adds a local native current-turn strip
using the server-selected SSE outcome, with strict validation and ephemeral state.
It clears on work/context changes and never enters stored history; physical-device
and live-Hub acceptance remain open. See `mobile/docs/h1833-turn-duration.md`.

H396 whole-turn outcome — current local source (2026-10-29): cockpit and focus chat
consume one request-owned `outcome` on JSON replies, SSE progress and SSE end. The
strip presents a consolidated source-assigned reason, proposed/queued/executed tool
counts and observed provider output or an explicitly labeled visible-text estimate.
Accepted tool results without a successful consuming model completion produce WARNING;
a normal answer does not claim objective success. Approved file attempts carry a
signed task/turn origin and physical-attempt identity. Bounded no-follow readback at
the effect boundary distinguishes verified, unverified and unknown; only a later
verified same-target attempt supersedes a failure. The footer uses ordinal/operation
and disposition, never a path or file contents. Closed replies cannot be rewritten by
later owner approvals. Native mobile currently reads latency only; the new completion,
accounting, output-flow and file-footer counterpart remains a mobile surface gap.
Synthetic source and mounted HUD tests are recorded separately from a live owner run.



### H444/H576 document input limit — 2026-10-09 local candidate

Parser-backed file_read now refuses observed PDF/DOCX inputs above 50,000,000
bytes before parser discovery. Existing tool-result handling carries the named
refusal and raw byte paging remains available. This is a backend admission check.
See `docs/project-document-input-limit-20261009.md`.

PDF reads now report significant ranges without extracted text in separate,
bounded tool-result metadata: more than 20% of pages or at least ten pages,
first 16 ranges, preceding 160-character source excerpts and explicit omitted
range counts. Text bytes and pagination are unchanged. Existing model/tool
handling carries the warning; a dedicated HUD PDF coverage card is not added.
This does not identify scanned content or run OCR. See
`docs/project-pdf-text-coverage-20261009.md`.

Explicit OpenRouter vision (H277, 2026-10-02): the existing composer model,
destination and policy display covers the new server-side provider. Its remote
checkbox still names the destination; live routing changes invalidate that
binding. The composer now displays separate unchecked training/cost confirmations
when requested by the server, requires all of them before send, and clears them
on image changes, refresh or draft clear. Unknown/malformed disclosures refuse;
remote acknowledgment is independent. Signed OpenRouter video remains unfinished.

Explicit DeepInfra vision (H277, 2026-10-02) now uses the existing composer. With
no explicit model, opening image status prepares a catalog selection; Refresh vision
destination forces a new catalog lookup and clears confirmations. Failed refresh
revokes the old selection. Metadata discovery sends no images, and remote inference
still needs the reviewed destination and any separate training/cost confirmations.
Native mobile acceptance remains open.

Nous account lifecycle (H277, 2026-10-02) is currently CLI plus owner API only:
login/status/poll/logout. The HUD has no Nous account-management controls yet.
This is explicit UI debt; account authentication alone does not select a provider.
Explicit Nous vision now uses the existing image composer, model/destination
display, refresh and confirmation controls. Status prepares an account-bound
recommendation; image POST only uses that prepared selection. Chat/Messages wire
changes invalidate confirmation. No account-management UI is claimed by this
server integration.

Opt-in automatic image selection (H277, 2026-10-02) shows the chosen provider
alongside its model and destination before remote confirmation. The server tries
OpenRouter, Nous and DeepInfra in order when available; the composer has no
selected main conversation route to reuse. Refresh may prepare metadata, while
image POST makes no replacement discovery. A provider or policy switch clears
the reviewed binding. Native provider controls and live acceptance remain open.
The composer now prepares a destination review for its current prompt and agent
and uses a one-use token for image submission. Prompt or agent edits invalidate
the visible review; a changed route, key or policy requires another review
before image bytes leave the server. This preparation still selects the
configured vision route rather than inheriting the active conversation backend.
Native image-review parity and live-provider acceptance remain open.

Selected main image turns (H277, 2026-10-02) now commit through
`/api/vlm/composer/chat-prepared` after the one-use review, session lease and
physical destination guard. The HUD restores the answer from `GET /memory`
using bounded image provenance. Standalone and auxiliary image descriptions
remain transient; native mobile image intake and live-provider acceptance are
still open.

H067 HUD stream continuation (2026-10-05): the actual /chat/stream emits live
clarification questions. The HUD offers choices, multiple selection, Other,
free text and cancellation, using the guarded /chat/pending/{prompt_id}/answer
route to resume the same model call. Only the original currently authorized
credential/role can answer; disconnect, expiry or credential revocation retire
the wait. Enable the existing Chat clarification preview and restart to use it.
Question delivery is acknowledged by the SSE generator before human-wait credit.
Rejected or failed answers remain visible for retry. Stop cancels the stream.
This closes the streaming HUD producer slice only; nonstream HTTP, email, CLI
and busy prose/other commands remain open under partial H067.

H067 nonstream HTTP continuation (2026-10-05): /chat uses the same authenticated
pending runtime. Concurrent GET /chat/pending (optional session_id, bounded
offset/limit) returns only the caller's live questions; the existing answer route
continues the original request. Delivery acknowledgement follows the discovery
response body, so failed sends cannot permit answers or human-wait credit.
The responsive HUD continues to use SSE. Native mobile has no pending question
picker/poller or answer UI; this API addition does not establish mobile parity.
CLI/email producers and busy prose/other commands remain open under partial H067.

Final inventory assessment (2026-10-05): H067's canonical gateway contract is
accepted as equivalent. The HTTP/HUD adapters above remain implemented. CLI,
email and ordinary busy-message improvements belong to their own contracts;
they were mistakenly treated as additional H067 gates in earlier checkpoints.
Native mobile interaction and full697/live acceptance remain open separately.

H660 resident execution continuation (2026-10-05): once code execution is enabled
and a pinned isolated image is configured, the existing kernel panel reports the
resident mode without a second opt-in. Explicit sessions=false remains an owner
override. Code cells and model-requested reset require an explicit GRANT; policy
is rechecked after the interpreter lock. No HUD/API schema or native-mobile
control is added. SSH/Modal/remote TLS and full integrated acceptance remain open.
# H595 new-message interruption — 2026-10-05

Backend HTTP/SSE and admitted channel routing now interrupt same-session code and
preserve bounded partial output/count/duration after teardown. The responsive HUD now sends intentional typed follow-ups during a text stream.
Each stream owns its reply bubble, controller and completion; Stop/unmount abort
and settle all pending streams. Pending answers retain their original controller,
and delayed callbacks cannot overwrite another reply. Vision remains exclusive
and voice does not open overlapping voice requests.
No new endpoint or fresh Docker/native-mobile acceptance is claimed here.


## FAL image provider (2026-10-06)

The registered image tool and media API dispatch approved FAL generation/edits
through the common worker. `/api/media` returns unprobed FAL configuration and
catalog IDs. The Images HUD now offers FAL, OpenAI and Codex provider/model
selection with capability-based reference entry, size and legacy OpenAI quality.
Decision Inbox cards show the actual provider and edit references; lost provider
metadata blocks a proposal instead of falling back to another provider.
Local artifact-reference upload to FAL, Clarity and managed OAuth setup remain open.
See `docs/hermes/openai-codex-image-guide.md`; no live provider acceptance is claimed.

## Image provider continuation (2026-10-06)

Images now offers OpenRouter, Krea, xAI and DeepInfra with explicit model controls
and provider-specific options. A saved inactive Krea job can queue a fresh GET
approval without another generation POST. DeepInfra's catalog refresh is an
approved GET with a local cache; it is not watched as an image task. Decision
Inbox shows the fixed endpoint, selected model or catalog operation, and immutable
Krea source job. Pending or rejected continuations cannot inherit ready artifacts.
See `docs/hermes/openrouter-krea-image-guide.md`. Explicit Krea Enhance is now
connected through a separate immutable source approval, 4K pixel/proof-bound
download/gallery/export and GET-only job continuation; original preview cleanup
and ambiguous submission are covered locally. Other donor
catalogs, FAL upload/Clarity, managed OAuth and native/mobile acceptance remain open.

## Signed model-provider installation (H361 source candidate)

The default-off owner API can stage a server-managed candidate, show a redacted
signed summary, record an exact permanent owner decision, promote and revoke it.
No dedicated HUD install/review flow is present yet. Package installation alone
does not change the active model or make another native dialect available; owner
selection, credential controls and live runtime/provider acceptance remain open.

## Named compatible endpoints — local integration (2026-10-29)

Console → Admin → Custom Endpoints now provides durable named `custom:<key>` entries, display-name aliases, create/rename/delete, exact revision/choice-epoch activation and clear, endpoint-scoped credential metadata/set/rotate/delete, and an explicit bounded `/models` validation. All ten routes under `/api/admin/llm/custom-endpoints` require the admin owner credential. Creation does not probe the destination; LAN/public creation and activation require an explicit destination grant. Validation displays a negative outcome as failure. A valid old signed selection is authenticated and rebound during upgrade; raw or stale selections remain inert. The CLI mirrors these operations under `nerva provider custom`; secret input uses stdin.

The new panel is a local implementation, with synthetic owner/Kernel/Vault/DNS/HTTP and mounted frontend checks. It does not close the separate signed-package HUD controls above, native-mobile configuration, live endpoint/device acceptance or the broader H361/H633 requirements. Capability proof classification and complete batch integration remain explicit gates.

## Governed browser sessions — local integration (2026-10-29)

Operator retains one-shot approval and adds fresh-profile start/act/close, bounded owner session/ref display and later browser-task outcome. The three session/task/close routes require the owner admin credential; generic availability remains user-tier. Grounded refs, scroll/back/press, frame/focus/native form semantics, current registration and exact per-step Kernel receipts are implemented. Local Chrome coverage includes unchanged-registration lifetime and changed-control native/journal cleanup. Console/get_images now add bounded completed-task untrusted observations through separate owner-approved reads, with conservative console invalidation and atomic image row/ref semantics. Vision/dialog/JS/CDP, other engines, real profiles, recording/spill, mobile controls and owner-host/live-platform acceptance remain required separately.


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

Local V44 (2026-11-13): extension inspection/host CLI now distinguish exact live declarations from currently callable tools and commands, using consent/package/registry checks. The dedicated HUD and mobile extension-inspection views remain pending; this diagnostic change adds no activation control.

### Local V51 — signed extension restart routes

Backend startup now restores owner-only command routes from saved activation hints and current consent, without running an extension or composing promotion. The first owner command revalidates package bytes and the exact consent grant before activation. Explicit admin activation may compose acquisition; read-only inspection still does not. Activation/revoke responses expose `restart_restore` separately from live success; `nerva extensions` prints persistence warnings. Build → Extensions remains read-only: no new HUD activation/revoke control is claimed. Native menu updates are queued after explicit activation/revoke and preserve the channel manager's pause/ownership guards. Live Docker/channel/browser acceptance remains unverified.

H697 local continuation (2026-11-13, V53): initial transcript rehydration and desktop cross-window refresh share exact missing-session recovery, coalescing current fallback reads and latching healed ids. A changed selection or started/completed turn fences late reads; malformed fallback snapshots cannot change selection. 403/409/503/network/proxy failures do not rebind. Reclaimed-session push integration remains open; this adds no new route or control.


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

2026-11-14 Lot 2 HUD reachability + H032 MoA presets: wired 13 previously uncalled backend routes into HUD v2 (`UNCALLED_BACKLOG` 54 -> 41) and added Console → Admin → MoA Presets (`MoaPresetsPanel`). `SubAgentsPanel` now exposes incremental transcript inspection (`/api/subagents/{id}/transcript`), final result lookup (`/api/subagents/{id}/result`), and batch completion claim (`/api/subagents/claim`). `A2AInboxPanel` adds outbound peer registry CRUD (`DELETE /api/a2a/peers/{name}`). `OAuthPanel` adds Nous Portal account status, PKCE login start, poll, and logout (`/api/oauth/nous/{status,login,poll,logout}`). `McpPanel` renders pending host elicitation cards and posts schema-typed answers (`/api/admin/mcp/elicitations/{card_id}/answer`). `ChannelDeliveriesDisclosure` adds `dead_targets` listing and `lift gone flag` (`/api/channels/dead-targets/clear`). `JobsPanel` adds durable incident acknowledgement (`/api/jobs/incidents/{incident_id}/ack`), cross-job recent runs (`/api/jobs/runs`), and structured KV notepad editing (`/api/jobs/{job_id}/notepad/keys`). `MoaPresetsPanel` manages `moa:<name>` committee presets, global activation, recent quorum/speedup telemetry, and one-shot governed synthesis over `/api/llm/moa/*`. Verified via backend parity/auth/OpenAPI gates and Vitest; live external provider and physical mobile device acceptance remain separate.
