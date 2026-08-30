# Changelog

## [Unreleased]

- **De-gated development (owner decision).** Removed every PR-blocking CI gate and scan:
  `security.yml` (gitleaks/semgrep/pip-audit/bandit), `ai-review.yml` (three AI reviewers per PR),
  `autonomy.yml` (tier/boundary classifier), `lockfile.yml`, `park-guard.yml`, `nerva-roadmap.yml`
  (roadmap-ledger validation), the Nerva movement gate in `ci.yml`, CODEOWNERS, the machine-readable
  AI-development policy + evidence-receipt PR template, and the pre-commit hooks. PRs now run one
  fast advisory lane (`ruff` + `pytest` on ubuntu, ~3 min); the Windows matrix, sandbox-isolation,
  HUD/frontend suites and OpenAPI typegen drift check moved post-merge (push to `main`), and
  CodeQL/e2e/smoke/code-health/eval/third-party-drift dropped their `pull_request` triggers.
  The matching branch-protection cleanup is an owner task (`docs/OWNER_TASKS.md` → "De-gate merges").

## [1.0.0] — 2026-08-28

The 1.0 line: every feature horizon (H1–H23 + WorldView O19) delivered, the productionization
spine done, and the owner gates closed. Release-gate changes in this cut:

- **A2 — the 72h soak grades itself.** `scripts/soak_report.py` gained `evaluate()`: the A2 bar is
  now written down as thresholds (availability ≥99%, zero restarts, zero audit-verify failures
  (AUD-0), zero guardrail breaches, no open circuit breaker, RSS growth ≤15%, WAL ≤64 MiB) instead
  of applied by eye. `--fail-on-verdict` turns the verdict into an exit code — PASS 0, FAIL 1, and
  **INCONCLUSIVE 3** for a window where some check had no evidence, so an ungraded soak can never
  read as a pass. The verdict is rendered into the report and written alongside it as
  `<day>-soak-verdict.json`.
- `--pid` is now optional: without it the collector records **no** RSS series rather than
  measuring its own process, and the leak check reports INCONCLUSIVE.
- **`.github/workflows/soak.yml`** runs the window unattended — boots the server, samples, grades,
  publishes the report to the run summary, uploads the evidence. A weekly canary on a hosted
  runner; the full `72h` via `workflow_dispatch` with a self-hosted `runner` label.
- Owner gates A4 (GitHub settings) and A7 (design partners) closed; A8's owner-host proof ran on
  real hardware with good feedback. A6 (60s demo cut) stays open as GTM work, never a tag blocker.
- `agents.__version__` `0.11.0` → `1.0.0`.
### Q10 — the public widget door is governed like the external input it is (2026-08-02)
- **ch11 CHN-061**: `widget` no longer sits in `INTERNAL_TURN_CHANNELS`. The embed endpoint is
  tier `open` — an anonymous visitor on a third-party site — so its turns now classify
  **`inbound`**, which taint-marks them (`inbound:widget`) and makes the kernel escalate a
  GRANTed action to QUEUE (owner approval) instead of letting it auto-execute.
- **ch11 CHN-060**: `POST /api/widget/{token}/message` routes through `Gateway.route` (via the
  new late-binding `app_state.get_gateway()`), so the per-channel rate limit and injection-flag
  detection apply. Deliberately **no `sender=`** — the pairing gate fails closed and would hold
  every anonymous message for approval — and deliberately **no inbox record**, since there is no
  widget reply adapter and a thread nobody can answer would be the dishonest option.
- A `None` from the gateway (its handler-failure path) maps to the documented
  `{"reply": "", "error": "request failed"}` envelope, so the embed shows an honest failure
  rather than its `(no reply)` fallback.
### Q8 — review→dataset promotion mints a real case, not a fabricated 1.0 (2026-08-02)
- **WFL-088**: `ReviewQueue.to_eval_case` emitted `{"input","expected",…}` — keys `run_dataset`
  never reads — so every promoted case replayed an **empty prompt** with no criterion, and the
  harness's "no criterion → pass by default" turned a flagged-as-bad answer into a perfect eval
  score. It now emits the documented `{"name","prompt","expect_contains","metadata"}` contract
  (promotion is idempotent per `trace_id`; `POST /api/review/{id}/dataset` accepts an optional
  reviewer `expect_contains` gold; `prompt_source` records that the preview may be truncated).
- **A criterion-less FILE case is now UNSCORED, never a pass** — `scored:false`, `score:null`,
  excluded from the aggregate (which is `null` when everything is unscored, never `0.0`), with
  `unscored:n` on the run. `EvalHarness._evaluate`'s pass-by-default is deliberately untouched:
  it stays a smoke-test affordance for ad-hoc lanes, while in the file lane `expect_contains`
  *is* the criterion (as the module contract has always said).
- **A promotion with no prompt is refused `400`** instead of minting a case that burns a live
  inference against an empty string.
### Q7 — workflow truth pair: parallel-batch honesty + built-in restore (2026-08-02)
- **WFL-032**: a step that *returns* `[error:…]` (timeout, validator, guardrail, subflow) inside a
  PARALLEL batch now fails the run exactly like the serial branch — before, `_ok` stayed `true`
  over a failed run (golden-rule class: `✓ Run complete` above a trace showing `ok: false`).
  With `JARVIS_WORKFLOW_PERSIST=1`, such runs now retry/park-dead in the durable queue instead of
  completing — the honest outcome.
- **WFL-036**: deleting a user pipeline that shadows a built-in id now RESTORES the pristine
  built-in in the live registry (`WorkflowRegistry.unregister`, from `_BUILTIN`) instead of popping
  it until restart; the route comment is finally true.
### Q5 — SEC-065 live guardrails-mode propagation + SEC-071 audit preview redaction (2026-08-02)
- **The posture screen and the live engine now agree without a restart** — `GuardrailsEngine.apply_settings`
  (name-keyed; garbage keeps the CURRENT mode) is re-pushed by the 30s settings watcher; `bind()` copies
  the mode per request, so the next turn scans under the new mode. A live flip rotates the prompt-cache
  key via `policy_fingerprint` (expected).
- **`content_preview` is masked at rest** — `AuditLogger.log()` redacts the preview (secret+PII scanners,
  the AUD-12 `[REDACTED:<pattern>]` convention) BEFORE the chain hash so stored rows verify; the turn seam
  redacts **then** truncates (`AuditLogger.preview`) so a 100-char cap can never split a key into an
  unmatchable raw prefix. `GET /api/admin/audit`'s `summary` alias shows the masked value.
### Q2 — /chat/stream parity: session notes injected; constant error bodies (2026-08-02)
- **`/chat/stream` now injects the session's notes block (H10.21) the same way `/chat` does** —
  persistent notes silently stopped applying the moment the cockpit switched to streaming
  (ch02 CHT-073 / open gap G3).
- **Both chat error paths return constant text** (`Internal error.` / `Eroare internă.`) instead
  of live exception detail — the py/stack-trace-exposure family that blocked #750; specifics stay
  in the server log.
### Q6 — kill-switch per-agent scope at the executor seam + stuck-RUNNING reaper (2026-08-02)
- **A per-agent halt now holds that agent's tasks at the tick** (`_halted(task.agent)` per task,
  same kernel-independent seam; held ≠ lost — tasks stay `approved` and run on release; summary
  gains `held`). The global pre-check and fail-open-on-broken-switch semantics are unchanged.
- **The worker now shares the orchestrator's own `KillSwitch` instance** — its lazy fallback
  built a second store that never reloaded the file, so a halt engaged after boot never reached
  the tick until a process restart (red-proven by revert-run).
- **`TaskQueue.reap_stuck_running(ttl)`** fails crash-stranded `running` tasks past
  `autonomy.running_ttl_seconds` (default 3600, live-resynced each tick, ≤0 disables) with
  `stuck_running_ttl` + `stuck_since` and an `autonomy.reaped` audit row — run at the top of
  every tick, even under a halt (honesty about a dead task is bookkeeping, not an action).
  In-process hangs stay the executor wall-time budget's job; the reaper exists for dead processes.
### A8-ii — presence-aware media target `presence:auto` (2026-08-02)
- **`target: "presence:auto"`** on `media.present` resolves the owner room's default device —
  gated on a **fresh `present` signal** from the H34.2 owner-presence store (the temporal half)
  plus **`JARVIS_MEDIA_PRESENCE_ROOM`** (the spatial half; unset keeps the target default-off).
  Idle/away/unknown/stale presence, a missing store, or an unset room refuse `presence_unknown` —
  a guess about where the owner is would be a lie. Room-level refusals pass through unchanged,
  every other target string resolves exactly as before, and the sentinel is branched before
  device-id lookup so a registered id can never shadow it.
### A8-iii — MediaDriver registry + the LocalFileMediaDriver reference driver (2026-08-02)
- **`JARVIS_MEDIA_DRIVERS`** (env, comma-separated; whole-list fail-closed like the sibling media
  knobs) binds real drivers into the route-owned `MediaDirector` — the `drivers=` seam existed on
  the class but `_get_director()` never passed it, so `NullMediaDriver` was the only reachable
  implementation and owner gate A8's media proof was unschedulable.
- **`LocalFileMediaDriver`** (`local_file` → device kind `local`): durable now-playing state under
  `data_path("media")/now_playing.json` that passes the full present/verify/restore rails and
  really flips to `idle` past a declared duration. Honest limits documented: no sound or image —
  it proves the governed rail before hardware is bought, not playback itself.
### fastapi 0.137 upgrade unblocked — route-introspection flattener (2026-06-19)
- **`fastapi` bumped to `>=0.137.2,<0.138`** (+ `starlette>=0.46,<1.0`). fastapi 0.137 wraps
  `include_router` results in an opaque `_IncludedRouter` instead of flattening them into
  `app.routes`, which collapsed the *introspected* route surface 296→83 and failed the route-parity /
  auth-matrix guards (the app was never broken — routes served + appeared in OpenAPI).
- **Fix:** `tests/_route_introspect.py::iter_effective_routes` flattens the wrappers via fastapi's own
  `_iter_routes_with_context` — yielding effective routes with merged `.path`/`.methods`/`.dependant`
  — and falls back to plain `app.routes` on fastapi ≤0.136. `test_route_parity_guard.py` and
  `test_route_auth_matrix.py` use it; **snapshots unchanged** (validated on 0.137.1: parity 296/296,
  auth-matrix 300/300, 0 drift, include-time guards resolve). Closes the hold tracked in #247.

### Maintenance — dependency upkeep, bug-table reconciliation, fastapi 0.137 hold (2026-06-19)
- **Dependabot triage:** merged the safe bumps — `actions/checkout` v6→v7 (#222), worldview-mcp dev
  deps (#223), root `vitest` 2→4 + `jsdom` 25→29 (#224). Held for dedicated review: React 18→19
  frontend (#226), WorldView 23-update group (#228), mobile group (#227, owner-gated). #237's harmless
  `pytest-xdist`/`ruff` dev bumps were split out from its held `fastapi` bump.
- **fastapi 0.137 held + root-caused (#247):** 0.137's `include_router` wraps included routers in an
  opaque `_IncludedRouter` instead of flattening into `app.routes`, collapsing the *introspected* route
  surface 296→83 and failing the parity / auth-matrix guards. The **app is unaffected** (routes serve +
  appear in OpenAPI); remediation + repro in
  `docs/research/2026-06-19-fastapi-0.137-include-router-regression.md`. Pinned `fastapi<0.137`.
- **MCP client `asyncio` NameError fixed (#243):** `MCPServer._send` awaited `asyncio.wait_for` with
  `asyncio` imported only inside `connect()`; the NameError was swallowed by a broad `except`, so
  **every** outbound MCP request silently returned `{}`. Hoisted the import + regression test
  (`tests/test_mcp_client.py`). Surfaced by `ruff F821`.
- **BACKLOG bug-table reconciled (#245):** BUG-3/6/7/8/9/10/11 were already fixed in code (with tests)
  yet still listed open — marked ✅ with fix location + guard test; BUG-12 → 🟡 (spend race closed via
  `_spend_lock`).

### Neural Mesh — live brain visualization of the orchestrator (2026-06-17)
- **`/brain` — the JARVIS Neural Mesh**, a live canvas "brain" of agents + models firing in real
  time (core node = the orchestrator, inner shell = models sized by cost, outer shell = agents,
  with token-flow particles animating along the attribution edges; hover to isolate, click to pin,
  drag to stretch). The visualization is adapted from **Axon's "NEURAL MESH" by Daniel Tamas**
  ([github.com/danieltamas/axon](https://github.com/danieltamas/axon)), used under the MIT License
  (retained in `LICENSES/axon-MIT.txt`).
- **`GET /api/brain/summary`** (`agents/core/routers/brain.py`) feeds it from the real request
  **tracer** — per-agent / per-model token + cost rollups, by-backend (local/claude/gemini)
  attribution, and a live recent-turns feed — seeded with the full agent roster so the mesh shows
  every node even when idle, then lights up the nodes with real traffic. `?range=today|7d|30d|all`.
  Both routes are `user_guard`-gated (localhost by default). 7 new tests (`tests/test_brain_summary.py`).
- **Dashboard integration** — the Neural Mesh now **replaces the agent-ring visualizer** in the
  primary v2 HUD cockpit (`frontend/src/app.tsx`): the network panel embeds the chrome-less mesh
  (`/brain?embed=1`) instead of the legacy SVG ring. `brain.html` gained an `?embed=1` mode that
  drops all chrome and renders only the full-bleed mesh. v2 bundle rebuilt; tsc + 19 v2 tests +
  184 legacy frontend tests green. (The legacy `/v1` HUD keeps its SVG ring.)

### WorldView — API never starts on Windows (2026-06-17, #204)
- **`worldview/backend-api/src/server.ts`** gated its auto-start on
  ``import.meta.url === `file://${process.argv[1]}` ``. On Windows `process.argv[1]` is a backslash
  path (`C:\…\server.ts`) while `import.meta.url` is `file:///C:/…/server.ts`, so the concat never
  matched → `main()` skipped → `app.listen()` never called → **nothing on `:4000`** (the frontend
  sat at "Reconnecting to the live feed… API may be offline"). Switched to the platform-aware
  `pathToFileURL(process.argv[1]).href` — the guard already used in `worldview/mcp/src/server.ts`.
  tsc clean, 218 backend tests pass.

### WorldView — two frontend dev-console warnings silenced (2026-06-17, #202)
- `app/layout.tsx`: `suppressHydrationWarning` on `<body>` (Grammarly/ColorZilla inject attributes
  before hydration — not a WorldView bug). `components/DeckGlobe.tsx`: deferred the `setZoom` store
  write out of Deck.gl's render-phase `onViewStateChange` (and skip when unchanged) — fixes the
  "Cannot update AppBar while rendering DeckGLWithRef" setState-in-render warning. tsc + 140 vitest
  tests + `next build` green.

### Security — synthetic OpenAI-key fixture defused (2026-06-17, #215)
- `tests/test_h10_4_guardrail_node.py` held a hand-crafted `sk-…` placeholder (a fixture for the
  guardrail/secret-scanner, **not** a real key) that GitHub secret-scanning flagged as a public
  leak. Built it by concatenation so the `sk-`+40-char shape never appears verbatim in source; the
  runtime value (and every assertion) is unchanged. No rotation, no history rewrite.

### CodeQL — correctness, ReDoS & log-injection fixes (2026-06-17, #216)
- **#248** (`skills/calendar/main.py`): `add_event` called `create_event(start=…, end=…)` but the
  plugin signature is `(summary, start_dt, end_dt)` → `TypeError` on every call. Fixed kwargs +
  corrected the test fake that mirrored the wrong signature and masked the bug.
- **#26** (`agents/core/heartbeat.py`): `SchedulerNotRunningError` was imported from the wrong module
  with a `= None` fallback → `except None:` `TypeError` in `stop()`. Import from `.base` with a real
  `Exception` fallback.
- **#1** (`agents/core/llm/base.py` `strip_thinking`): rewrote the leading-numbered-step regex to a
  linear form (`^(?:\d+\.[ \t][^\n]*\n)+\n`) — the old `\s+.+` backtracked super-linearly.
- **#302** (`workflows/hierarchical.py`): made the `_render` template group possessive `\{([^}]++)\}`.
- **#311 / #24** (`agents/web.py`, admin-only routes): routed user input through `log_safe()` before
  logging (CR/LF log-forging). The path-injection alerts #22/#23/#431 are false positives (the
  agent-id regex `^[a-z0-9_-]{1,64}$` forbids separators) — dismissed in the UI, not patched.

### WorldView — full UX redesign implemented from the Claude Design spec (2026-06-12)
- **The complete TASK-4 WorldView redesign** (`docs/design/WORLDVIEW_UX_SPEC.md`, all 11 steps),
  on top of the tactical fixes from PR #193: brand-unified tokens (void/surface/signal `#2BB8F0`,
  Space Grotesk + JetBrains Mono via fontsource), an app bar + two-rail **zone system** (no more
  absolute-offset panel collisions), a three-signal **mode system** (2px frame + pill with GO LIVE
  + timeline restatement; DEMO watermark bound to feed source), **Legend=Layers** with the real
  map glyphs + live counts, de-collided **shape+color map encodings** (canvas icon atlas with
  circle fallback; military=amber hollow chevron, red reserved for wrong), the **negative-space
  grammar** (signal-loss ghosts, dashed dead-reckoned paths, uncertainty cones, voided-zone
  outlines — never animated, never invented), humanized **Inspector** with dark-vessel alert
  context + plain-words provenance, first-run overlay per spec copy, timeline **event markers** +
  store-lifted replay window, styled tooltips, help overlay from a shared shortcut map (+`1–5`,
  `G` bindings), and the **arrival deep link** (`?from&to&layer&id&lon&lat&zoom&agent` → camera
  pre-positioned, entity selected, REPLAY from frame one, Argus banner) + the optional demo lens.
  39 new frontend tests (140 green), tsc + `next build` green. Design package + impl: PR #194.

### UX — first-run onboarding + pre-test review (2026-06-10)
- **First-run guidance banner** (HUD `app.tsx`). Booting the real bundle in a browser confirmed a
  fresh install (server up, no model, no plugins — the manual-test starting state) showed a wall of
  "not connected" with no next step. Added a dismissible, model-aware welcome strip ("start LM
  Studio…" / "connect plugins in Admin") with one-click demo preview; remembered in localStorage.
  tsc + 19 frontend tests green, bundle rebuilt.
- **Deep UX review of both frontends** → `docs/2026-06-10-ux-review-hud-worldview.md` (triaged P1/P2/P3,
  verified the honesty system + design visually). Remaining items tracked as BACKLOG TASK-4 for a
  focused post-manual-test pass — deliberately not bulk-fixed before the human gate.

### Diagnostics — surface a silent OAuth failure + CLN sequencing (2026-06-10)
- **`oauth.load_token` no longer swallows a decrypt failure.** A rotated/missing secret key or
  corrupted token file silently left the still-encrypted token in place — the connected service
  (Gmail/Calendar/Spotify) would then fail mysteriously with no trace. Now it **warns** ("re-
  authorize the service"), so the owner can diagnose it during the manual-test run. +1 test.
- Telegram cosmetic calls (callback-ack, typing indicator) and the Qdrant collection probe:
  documented their intentional swallows (debug log / comment) so they're no longer indistinguishable
  from a missing handler. (Surveyed all 355 `except` blocks; the rest are legitimate documented
  graceful-degradation — left as-is to avoid log noise.)
- **CLN-2/CLN-3 (god-object split) sequenced post-1.0** by owner decision — a 5,000-line refactor
  carries regression risk that shouldn't land before the human manual-test gate. Recorded in
  BACKLOG + OWNER_TASKS.

### API honesty — two inconsistencies found by running the app (2026-06-10)
- **`GET /api/agents/{id}/history` 404s for unknown agents**, consistent with `/soul` (it
  was returning a misleading `200 + empty runs` for any id, so a typo'd agent looked real
  with no history). Also validates the id against the agent-id alphabet.
- **`POST /learning/promote` of a nonexistent bench agent returns 404 / `ok:false`** instead
  of the old `{ok:true, promoted:false}` that reported success for a no-op. +3 endpoint tests.

### Governance audit pass 3 — 3 promises hold, 1 defense-in-depth gap closed (2026-06-10)
Verified four governance promises against the code (the method that found BUG-14..17):
- **Autonomy risk gate ✅ holds** — ASK-tier tasks go to BLOCKED, `runnable()` queries only
  `approved`, night-shift `max_tier` is enforced at the SQL level, edits are re-gated. An
  irreversible/money task cannot execute without explicit approval.
- **Interrupt budget ✅ holds** — `consume()` gates before every push and again at execute
  time; day-rollover is atomic; the 5th interrupt is held for daily review, not dropped.
- **Capability tokens ✅ hold** — expiry is checked at USE time (not just issue), scope is
  fixed at issue, `authorize()` requires both the token and the kill-switch.
- **Injection quarantine — wired into the untrusted-input gate.** The quarantine primitives
  existed but weren't invoked on the path that turns untrusted text into actions. *Corrected
  severity:* not a critical exploit (chat agents return text, never call mutating tools; the
  only text→task path — transcript ingest — is already hard-forced to ask-tier=3, so nothing
  auto-runs). Closed the defense-in-depth gap: transcript ingest now runs `detect_injection`
  and surfaces `injection_flags` + an `untrusted_source` marker on the **approval card**, so
  the human gate is informed when content is tainted. +1 test. Broader "taint-track every
  external channel" left as a tracked finding (architecture decision — see BACKLOG TASK-3).

### Stability & UX — found by running the app as a first-time user (2026-06-10)
Booted the server and walked the journeys a new user hits before loading a model:
- **Friendly "no model loaded" message.** A fresh install with no LLM returned a raw
  `[jarvis error: No LLM backend available]` as the chat reply — the single most common
  first-run state, with the least helpful message. Now every channel (web/telegram/discord/
  CLI) returns one actionable line: "No language model is loaded yet. Start LM Studio (or
  Ollama)…". Fixed centrally in the orchestrator's agent-call handler.
- **`AGENT_COUNT` no longer drifts.** `/api/status` (consumed by the HUD) reported 16 active
  agents while the roster was 17 — a hardcoded constant. Now computed from the canonical
  registry (`agents.yaml`) with a registry-pinned regression test.
- **Blank turns rejected.** An empty/whitespace `/chat` message was accepted and spent a full
  routing + LLM turn; now rejected with 422 before reaching the orchestrator (`min_length` +
  a not-blank validator). Cheap no-op for an accidental Enter.

### Security — governance promises verified against code, 3 fixes (2026-06-10)
Second docs-vs-code audit pass (same method that found BUG-14):
- **BUG-15 — Howard could reach the cloud.** `_select_howard_backend` short-circuits
  *before* the policy gate, and its last resort was Gemini (`cloud-fallback`) — for the
  LOCAL_ONLY digital twin holding the owner's conversation archive. Now fails closed,
  like Frigga (BUG-14). +1 test.
- **BUG-16 — `llm.cloud_fallback` was a dead knob.** The /admin privacy setting
  (`never|on-demand|always`) was defined and rendered but read by NOTHING — an owner
  selecting "never" still got cloud spill. Now honored live in `HybridRouter`
  (`never` keeps auto-policy agents local even oversized; `always` prefers cloud;
  `on-demand` = previous behavior), re-synced ≤30s by the settings watcher. +6 tests.
- **BUG-17 — the Merkle audit chain was never verified.** `AuditLogger.verify_chain()`
  had zero callers — "tamper-evident" without an evidence check. New
  `GET /api/security/audit/verify` returns `{valid, first_invalid_id, entries}`;
  unit tests prove real tampering and re-linking are detected. +5 tests
  (HUD surface queued in the TASK-2 punch-list).

### Security — strict-local agents fail closed (BUG-14, 2026-06-10)
- **Frigga could reach the cloud.** `HybridRouter.select_backend` with `policy=local` fell
  back to Gemini (`cloud-fallback`) whenever the local backend was down — and a unit test
  enshrined it. This contradicted non-negotiable principle #1 (MOONSHOT §5.1, AGENTS.md:
  "no external calls, no cloud fallback — ever"). Now `policy=local` **fails closed** with an
  explicit error; tests assert frigga is never routed off-machine even with cloud available.
- **`agents.yaml` `llm_policy` is now honored** in routing (it was silently ignored —
  Argus was registered `claude` but routed `auto`). Resolution order: `LOCAL_ONLY_AGENTS`
  security floor (code-enforced, registry can't override) → registry `llm_policy` → in-code
  fallback sets → `auto`. +3 tests; ARCHITECTURE §5 updated.

### HUD v2 depth pass — UI controls for the 2026-06-09 backend wave (2026-06-10)
- **TASK-2 control gap closed** (PR #181) — the parity re-audit found ~37 backend endpoints
  with no HUD v2 control; all now have live surfaces:
  - **Cockpit:** live cognition over SSE (`/api/cognition/stream`, NTH-1) — routing decisions
    stream into the trace as they happen; the post-turn snapshot stays as fallback.
  - **Trust:** payment approve/reject/settle on the real broker ids (H16.3); sender-pairing
    approvals + pairing code (H12.19); prompt-injection scanner (H17.1).
  - **Autonomy & Agents:** heartbeat run/start/stop; transcript→governed-tasks ingest (H12.25);
    escalation targets + send (H12.11); bench promotion (`/learning/promote`); agent templates
    (H10.29).
  - **Build:** AI step builder (H10.7); sandbox execute with honest DEV_MODE 403; marketplace
    review ✓/✕ (H12.12).
  - **Memory/Observe:** nightly-reflection status + run-now; eval dataset runs + compare.
  - **Admin:** LM Studio server start / model load / unload; cloud auth-profile pools (H12.20).
- Admin-guarded Console actions now send the admin token (`actA`) instead of relying on the
  localhost exemption (kill-switch, A2A decide, capability issue, marketplace review, promote).
- `frontend/`: +7 tests (19 total) — payments/review/promote helpers, PairingPanel decide flow,
  SandboxPanel execute + 403 honesty. `tsc` clean; bundle rebuilt to `agents/web/v2/`.
- Punch-list updated: `docs/design/HUD_V2_REMAINING.md` §10 (remaining tail: plugin-gated mode
  wiring, per-panel LIVE/SEED chips, §6 toolchain, locality endpoint).

### HUD voice loop — hands-free voice in the browser (2026-06-07)
- **Browser voice loop** (PR #162) — the HUD mic button was a dead toggle and the voice
  engines only worked for a host-attached mic. New `frontend/src/voice.ts` (`useVoice`)
  captures mic audio (`getUserMedia` + `MediaRecorder`), VAD-segments an utterance, sends it
  to **local Whisper** via `POST /api/voice/stt` (raw body — deliberately no `python-multipart`),
  hands the transcript to the chat turn (`app.tsx: runTurn`, now promise-returning), and
  **speaks the reply** — server `/tts` (cloned voice) with a fully-local `speechSynthesis`
  fallback. Loops hands-free until toggled off.
- **Honest capability reporting** — `GET /api/voice/capabilities` (`{stt,tts,tts_local,providers}`)
  drives the HUD; STT returns `503` + install hint when `faster-whisper` is absent rather than
  fabricating a transcript. `tests/test_voice_stt.py` (+4 mocked, headless).
- **Voice settings** (persisted `localStorage['hud.voice']`, ⚙ popover): hands-free vs
  push-to-talk, speak via server/browser/off, language auto/RO/EN; respects `JARVIS_MIC_MUTED`.
- **Opt-in barge-in** (PR #164, default OFF, experimental) — sustained over-talk above an
  echo-resistant threshold cancels the spoken reply so the loop captures you. Renamed the SPEAK
  option `CLONED`→`SERVER` (it is your cloned voice only when XTTS is configured).
- Docs: `docs/VOICE.md` (new); `docs/ARCHITECTURE.md` §3 + Doc Map updated; BACKLOG H5.16 corrected.
- ⚠️ Live mic/audio + barge tuning need a real device — verified here by `tsc`/`vite build` +
  mocked STT test only.

### Security — Romanian PII detection (2026-06-01)
- **`PIIScanner` now detects Romanian identifiers** (`core/security/scanner.py`),
  closing the long-standing gap between the docs ("Romania-specific, CNP format")
  and the US-only implementation:
  - `ro_cnp` — national ID (CNP), **CRITICAL**, confirmed by the official
    control-digit checksum + birth month/day plausibility, so arbitrary
    13-digit numbers are not flagged.
  - `ro_iban` — Romanian IBAN, **HIGH**, confirmed by the ISO 7064 mod-97
    checksum (case-insensitive, space-tolerant).
  - `ro_phone` — Romanian mobile (`07…`, `+407…`, `0040…`), **MEDIUM**.
  Matches for the checksum-bearing patterns must pass their validator before
  being reported or redacted (a non-CNP 13-digit run is left untouched).
  Exposed `is_valid_cnp` / `is_valid_iban` helpers.
- **First direct test coverage for the scanners** — `tests/test_security_scanner.py`
  (+27 offline tests) covering `SecretScanner`, the existing generic PII patterns,
  the new RO detectors (valid vs. invalid checksum), and `GuardrailsEngine`
  REDACT/BLOCK/WARN behaviour.

### H5.17 Batch & Cache Embeddings (2026-06-01)
- **H5.17 Batch & Cache Embeddings Pipeline** (`core/ingestion/embedder.py`):
  `EmbeddingCache` — content-addressed (`sha256(namespace\x00text)`), sharded,
  crash-safe (atomic temp→rename), with hit/miss stats. `Embedder.embed_batch`
  resolves cache hits first, de-duplicates, and computes only misses (optionally
  across a thread pool). Each backend call is retried with exponential backoff
  and **degrades to the hash embedding** when the budget is exhausted, so a flaky
  rate-limited call never aborts a massive Howard ingest. Cache namespaced by
  `backend:model`; pipeline logs `cache_stats` in Phase 6. +9 offline tests.

### QA pass + Retrieval Fusion (2026-06-01)
- **H5.14 Retrieval Fusion Engine** (`core/memory/fusion.py`): `reciprocal_rank_fusion()`
  (rank-based RRF, no cross-scale normalization, with source provenance + payload
  merge) and `HybridRetriever` blending the vector store (Qdrant/in-memory) with
  the knowledge graph (Neo4j/in-memory); injected + duck-typed, so it is tested
  offline. Exposed as `MemoryManager.hybrid_search(embedding, keyword, top_k)`.
  +9 tests. Plan: `docs/superpowers/plans/2026-06-01-h5.14-retrieval-fusion.md`.
- **Test isolation fix** (CI red → green): `web.orch` leaked across test files,
  causing 2 order-dependent failures (`test_oracle_endpoints`, `test_agent_soul_endpoint`).
  Made the FastAPI `lifespan` teardown symmetric (guarded reset of `orch`/`gateway`
  on shutdown, so a closed `TestClient` context stops leaking a live orchestrator)
  and restored the global in `test_resilience_integration._admin_response`.
- **Backlog sync**: confirmed **H5.12** (Secured Shell Task Executor — `RemediationRunner`)
  and **H5.13** (Proactive Event Watchers — `EventWatcher`) were already delivered,
  wired and tested; marked done. Full suite: **749 passed, 9 skipped**.

### MCU Gap Analysis audit (2026-05-31)
- **FAZA 2 — Intent router rewrite** (`core/router.py`): replaced the v0.1
  keyword stub with a deterministic, offline-first, **scored bilingual (RO/EN)**
  classifier. Fixes substring misroutes ("car"⊄"scared"), routes Romanian
  queries ("câți bani am?"→Gecko, "cum am dormit?"→Hercules), exact-token wake
  words, confidence + score breakdown on `Intent.context`, canonical
  language-independent `keywords_found` tags, and an optional injected LLM
  fallback used only for unmatched/low-confidence input (zero hot-path latency).
  Drop-in: unchanged `classify()`/`Intent`/`ROUTING_TABLE` contract. +47 tests.
- **FAZA 3 — Proactive OS Observer** (`core/autonomy/observer.py`): the missing
  trigger layer. Samples host resources + service liveness, **debounces on state
  change**, and feeds the existing autonomy queue — plain alerts auto-approve
  (HUD/brief), remediation proposals (e.g. "restart Docker?") become tier-3 ASK
  cards in the decision inbox. Injectable probes (offline-testable). Wired into
  `_autonomy_loop` (gated by `system.observer_enabled`) + `/autonomy/observer`
  endpoints. +15 tests. Full suite: **715 passed, 8 skipped** (after reb: H5.9/H5.10).
- `docs/gap-analysis-mcu-jarvis.md` — full audit on 4 axes + OSS benchmark.

### H4 Platform
- **H4.5 Steve System Monitor** — `skills/system_monitor/` skill with 8 commands:
  - `status`, `cpu`, `ram`, `gpu`, `disk`, `temps`, `services`, `check`
  - Auto-recovery for configured services (ollama auto-restart)
  - Alert thresholds: CPU >80%, RAM >85/95%, GPU temp >85°C, disk >80/90/95%
  - Graceful degradation when psutil or nvidia-smi unavailable
  - 24 tests passing
- **H4.9 Guardrails** — already implemented and integrated (WARN/REDACT/BLOCK modes)
- **S0.2 Heartbeat Sanity** — already completed (Steve 2h, Ultron 2x/day)
### H1 Foundation (completed)
- Voice channel with wake word → STT → orchestrator → TTS pipeline
- Telegram channel with session isolation per `chat_id`
- Web channel with streaming, temperature/max_tokens/model from settings DB
- OAuth module (Google Calendar, Gmail, Spotify) with auto-refresh
- Admin DB → runtime settings with 30s refresh watcher loop
### H2 Core Agent Capabilities
- Pepper email triage routing: `email` keyword targets [pepper, veronica, stark]
- WebSearchPlugin: Tavily / SearXNG / DuckDuckGo fallback chain
- Vision agent wired with websearch plugin
### H3 Intelligence
- Heartbeat scheduler (APScheduler) wired in channel startup
- Bench agent activation — failure tracking, promotion/demotion in orchestrator
### H4 Platform
- Discord channel conditioned on `DISCORD_BOT_TOKEN`
- Email channel conditioned on `SMTP_HOST` + `IMAP_HOST`
- Slack channel conditioned on `SLACK_BOT_TOKEN`
### Cross-cutting
- 39 tests all passing

## [0.2.3] — 2026-05-30
### Fixed
- SSE deduplication: `\n\n` split across TCP chunks no longer creates duplicate messages
- Loading/offline indicators in HUD when API is down
- Admin channels panel now shows all 6 channels (including discord, email, slack)
- Deduplicated `AGENT_GLYPHS` — now uses `window.JARVIS_GLYPHS`
- Recycled `VoiceVisualizer` component (~120 lines) and dead CSS (~85 lines)
- Removed unused `SettingsPage` component

## [0.2.2] — 2026-05-30
### Fixed
- Thread-safe settings DB access with `RLock`
- Dynamic agent ring: `intent.target_agents[0]` fragile indexing
- Memory attribution — each agent's memory stays isolated
- Tests: `conftest.py` fixture isolation, `pytest.ini` config
- QA bug plan documented in `.opencode/plans/qa-bugs.md`

## [0.2.1] — 2026-05-30
### Added
- **HUD redesign**: fully offline-capable SPA with vanilla React (no JSX)
  - Admin panel at `/admin` — settings, channels, agents, audit, test LLM
  - Components: `ChatWindow`, `Sidebar`, `AgentOrchestrator`, `SystemTray`, `SettingsPage`
  - Font system: 31 custom woff2 fonts from JetBrains Mono + Cascade Code
  - Animations: network graph (`network.js`), auto-scroll, theme toggle
- **New plugins**: Apple Health, Google Calendar, Homebridge
- **Gemma 4 31B** as default LLM via Ollama
- **Settings DB**: SQLite-backed settings with admin CRUD, reseed, dynamic `force` flag
- **Security**: guardrails engine with PII detection, prompt injection blocking
- **Sandbox**: code execution isolation layer for agent tools
- **Plugin gate**: permission-based plugin access control
- **Tests**: routing, chat, sandbox/gating, startup — 39 total
- **One-click install**: `install.ps1` — virtualenv, deps, Ollama pull, startup
- **`.env.example`**: config template for all channels, OAuth, plugins

### Changed
- Monolithic `app.js` split into `components.js`, `enhancements.js`, `data.js`, `network.js`
- `style.css` reorganized: 1750 lines with density/theming support

### Removed
- JSX build step — vanilla `createElement` throughout
- External CSS/font dependencies — fully self-contained

## [0.1.0] — 2026-05-27
### Added
- Initial commit: Jarvis v0.2.1 multi-agent AI orchestration system
- Multi-agent orchestrator with routing, context, streaming
- Web UI with chat, system tray, agent status
- Plugin system: Weather, News, Gmail, Telegram, Spotify, WhatsApp
- Voice pipeline with wake word detection
