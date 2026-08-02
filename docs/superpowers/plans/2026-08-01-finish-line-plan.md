# Finish-Line Plan — the 10-Hour Autonomous Run (and the road to 1.0)

> **Status:** approved 2026-08-01 (owner session) · merge policy for the run: **auto-merge on green** (owner-approved)
> **Executor:** any Fable session on this repo, using the prompt in Appendix A. BACKLOG.md stays the priority ledger.
> **Companions:** `AGENTS.md` (conventions) · `docs/AGENT_WORKFLOW.md` (finish-branch protocol) · `MOONSHOT.md` §4 (gates) · `NERVA_VISION.md` §10 (v1 bars) · `docs/OWNER_TASKS.md` (owner lane).

---

## 1. Mission + definition of done for the run

Execute the ordered queue in §3 top-to-bottom for 10 hours: **one item = one PR**, each driven to a squash-merge on green CI. Done means: every attempted item is either **merged** (SHA recorded), **parked** (draft PR + journal entry), **skipped-owner** (one-line question logged to BACKLOG), or **cut** (60% rule) — with main green, no uncommitted work, and the §3 status column + BACKLOG refreshed. Target: 8 code PRs + 1 docs PR at plan velocity; the A8-unblocker subset (C1–C4) is the minimum honorable outcome.

## 2. Ground truth: the gate model, and why this queue

**1.0 = Phase 2a AND Phase 2b (MOONSHOT §4, gates cannot be skipped):**
- **2a Proof track (owner-led, A1–A9):** ⭐B0 manual run · 72h soak · Dependabot tail · GitHub settings · license flip · demo+landing · 1–3 design partners ≥2 weeks with real north-star data · **A8 AI-OS owner-host proof** · tag.
- **2b Six pillars at their v1 bars** (NERVA_VISION §10), verified by the reality harness, never asserted.

**The ranking argument:** the owner is the scarce resource. Per `docs/OWNER_TASKS.md`, **A8 is unschedulable today because product code is missing**: (i) no HTTP/HUD trigger for the H32 acquisition loop; (ii) no presence→media-target binding; (iii) only `NullMediaDriver` ships (the `drivers=` seam exists on `MediaDirector` but `routers/media_director.py::_get_director()` never passes it); (iv) `ungoverned_actions == 0` is measurable only in hermetic packs. Only the A8 unblockers convert future owner-hours into gate progress, so they lead. S8 (fresh install → first accepted autonomous action < 30 min) makes TTFV item Q11 the opener. The riskiest L (Q1) runs mid-shift with warm machinery, never first.

**Non-goals for the run:** no default-off flags flipped on · no owner-lane items attempted (A1–A9, GPU, license, GitHub settings, hardware/credentials) · no product-behavior choices beyond stated acceptance criteria · H34.3 dev-swarm feed deliberately **cut** (zero gate impact) · no pushes to main.

## 3. The run queue (main lane, ordered)

Status column = the committed ledger; update it inside each item's own sync commit (never a separate PR).

| Cycle | ID | Item | Size | Primary files | Status |
|---|---|------|------|---------------|--------|
| C1 | Q11 | `.env` token load order (ENV-039) | S | `agents/web.py` + env read sites | ✅ merged #749 |
| C2 | QA1 | A8-i: acquisition-loop HTTP trigger + contract factory | M/L | `agents/core/routers/acquisition.py`, `agents/core/acquisition/runtime.py`, `agents/core/acquisition/llm_synth.py` | ✅ merged #750 |
| C3 | Q15 | A8-iii: MediaDriver seam + `LocalFileMediaDriver` reference | M | `agents/core/routers/media_director.py`, `agents/core/media_director.py` | ✅ merged #751 |
| C4 | QA2 | A8-ii: presence-aware media target (`presence:auto`) | M | same files as C3 → **serialize after C3** | ✅ merged #753 |
| C5 | Q1 | Streaming multi-agent synthesis + per-agent route_name | L | `agents/core/orchestrator.py` | ✅ merged #752 |
| C6 | Q6 | Kill-switch per-agent scope in worker tick + stuck-`running` TTL reaper | M | `agents/core/autonomy/worker.py`, `agents/core/autonomy/queue.py` | ✅ merged #754 (retry 1: pack pin) |
| C7 | Q2 | Stream notes parity — **actually the web layer** (`agents/web.py`), not `orchestrator.py`; independent of Q1 | S | `agents/web.py` | ✅ merged #755 |
| C8 | Q5 | SEC-065 live guardrails-mode propagation + SEC-071 audit preview redaction | M | `agents/core/security/guardrails.py`, settings watcher, `agents/core/security/audit.py` | ✅ merged #756 (retry: stale-head refresh + one infra re-run) |

**Stretch lane (strict order, only if ahead):** QA4 live ungoverned-actions counter (`/api/metrics/kernel` + intent-log mediation ratio) → Q7 workflow truth pair (WFL-032/036) → Q8 review→dataset mint (WFL-088) → Q10 widget ingress gateway+taint → Q12 seeded-corpora DEMO labels + cockpit decision-queue wiring (SHL-102/103) → Q9 email reply dispatch branch → Q14 R8 repro-first → Q13 SEC-B6 read-gate ratchet → Q4 wave-E off-loop I/O (grep for call sites; the old list named a nonexistent `routers/onvif.py`) → Q16 catch-up notes.

**Stretch-lane status (final, 2026-08-02):** Q7 ✅ #774 · Q8 ✅ #775 · Q10 ✅ #776 · **QA4 PARKED** (design flaw — see `2026-08-02-qa4-ungoverned-counter-park.md`) · Q12/Q9/Q14/Q13/Q4/Q16 ⬜ not started. Main-lane C1–C8 all merged (#749–#756).

## 4. Schedule + cut protocol

| Clock | Activity |
|-------|----------|
| T+0:00–0:25 | Boot checklist (§11); baseline full suite in background; journal skeleton |
| T+0:25–1:10 | C1 implement+verify; push ≈T+1:05 |
| T+1:05–2:35 | C2 during C1's CI (disjoint); C1 merges ≈T+1:20; push C2 ≈T+2:35 |
| T+2:35–3:45 | C3 during C2's CI; push ≈T+3:45 |
| T+3:45–4:00 | C3's CI window: do NOT start C4 (same files) — subagent recon brief for Q1 instead |
| T+4:00–5:00 | C4 from merged-C3 base; push ≈T+5:00 |
| T+5:00–7:00 | C5 (the L), from the recon brief; push ≈T+6:50 |
| T+6:50–7:45 | C6 during C5's CI (disjoint); push ≈T+7:45 |
| T+7:45–8:20 | C7 (needs C5 merged); push ≈T+8:15 |
| T+8:15–9:15 | C8; push by **T+9:15 = hard last-PR cutoff** |
| T+9:15–10:00 | Babysit CIs; fix-or-park by T+9:30; ledger + BACKLOG rollup; final report |

**Checkpoints (even hours):** merged-PR floor 1 by T+2, 3 by T+4, 4 by T+6, 6 by T+8. At ≤60% of floor: keep only **Q11+QA1+Q15+QA2+Q1+Q2**; cut order (first cut first): Q16, Q14, Q9, Q12, Q10, Q8, Q7, QA4, Q4, Q13, then Q5, then Q6. If Q1 runs >150 min without a green local suite: park it, pull C6+C8 forward. **Per-item caps:** S=60 / M=100 / L=160 min (implement→push, excluding CI).

## 5. The cycle protocol (mechanical)

1. **SYNC** — `git fetch --prune origin` (prune kills the ghost refs squash-merge auto-delete leaves) → `git rebase origin/main` on the work branch (or `git checkout -B <branch> origin/main` between items). Journal `N START`.
2. **RED** — bugfix items: write the failing regression FIRST, run it targeted, confirm it fails for the expected reason, journal the red line. Feature items (QA1/Q15/QA2): contract test first anyway.
3. **GREEN** — minimal implementation. New routes go in `agents/core/routers/<domain>.py`, never inline in `web.py`. Targeted pytest plain: `python -m pytest tests/test_x.py -q --tb=short`.
4. **SURFACE DECISION TREE** (run every branch that applies, before the full suite):
   - *Routes added/changed* → `python tests/test_route_parity_guard.py --update` · `python tests/test_openapi_parity_guard.py --update` · hand-edit `tests/_snapshots/route_auth.json` rows · `python scripts/gen_api_sweep.py` · if handler signatures/docstrings changed: boot the server on :8765 and `npm --prefix frontend run typegen:openapi`, commit `schema.gen.ts`.
   - *Action kinds/capabilities changed* → capability manifest + matrix exerciser (kernel-on AND kernel-off legs) + `tests/_snapshots/action_auth.json` + `python tests/test_capability_readiness_matrix.py --update` + H27 pinned counts.
   - *`frontend/src` changed* → `npm --prefix frontend run test` (vitest) · `npm --prefix frontend run build` · **commit the regenerated `agents/web/v2` bundle** (CI gates on it).
   - *User-facing endpoint added* → HUD wiring or `docs/design/HUD_V2_REMAINING.md` punch-list entry + `mobile/PARITY.md` row, same PR.
5. **FULL VERIFY** — background Bash: `JARVIS_TESTING=1 python -m pytest tests/ -n auto --dist loadfile --timeout=90 -q --tb=short > <journal_dir>/N-full.log 2>&1; echo exit=$?` — read the exit from the file/echo, **never from a pipe**.
6. **SYNC-IN-PR** (last commit, minimal lifetime): `python scripts/status_sync.py --reuse-js-counts` (full sync only when JS tests changed) · BACKLOG row tick/annotation · test-manual chapter annotation when the item came from `docs/test-manual/*` · §3 status column update.
7. **PUSH + PR** — `git push -u origin <branch>` · create PR (non-draft) with the exact verification commands + results in the body · `enable_pr_auto_merge` (squash) · `subscribe_pr_activity`. Journal `N PUSHED pr#`.
8. **PIPELINE** — start item N+1 implementation only if its file footprint is disjoint (serialized pairs: **Q15→QA2**, **Q1→Q2**). Never open PR N+1 before PR N merges. CI windows without a pipelinable item = subagent recon brief for a later item.
9. **ON EVENTS** — *merged*: `git fetch --prune`, rebase pipelined branch, journal `N MERGED <sha>`. *CI red*: digest the failing job log **via a subagent** (`get_job_logs` output is a context bomb); classify legit / windows-only / infra-flake (flake = one free job re-run); fix and push; `retries[N] += 1`; at 2 → **PARK** (§8).
10. **HOUR BOUNDARY** — rewrite the journal STATE BLOCK + one-paragraph honest report.

## 6. Per-item implementation briefs

- **Q11 (ENV-039):** `JARVIS_ADMIN_TOKEN`/`JARVIS_USER_TOKEN`/`DEV_MODE` are read at module import in `agents/web.py` (~:48,:62,:147,:218) while `load_dotenv` runs later in `PluginManager.build()`. Prefer **lazy reads at request/guard time** over moving `load_dotenv` (import-order blast radius). Regression: token set only in `.env` activates the guard; verify with `tests/test_lifespan_smoke.py` + a new targeted test. Watch `_user_token_required` claims-to-match-the-guard docstring (SEC-031 adjacacy — fix if trivially in scope, else note).
- **QA1 (acquisition trigger):** `AcquisitionRuntime.synthesize_and_propose` exists and is tested (`acquisition/runtime.py:168`, guard at :213); the router exposes only status/events/ledger/export/purge/revoke/rollback. Add admin-guarded drive route(s) (e.g. `POST /api/acquisition/{request_id}/drive`) building the contract via a factory, research via **SearXNG only** (`research.py:76-84` rejects Tavily — also fix the OWNER_TASKS overstatement in-PR), generation via `llm_synth` with `LLMRouter.local_backend`. Honest degrade when SearXNG/local LLM absent (`_degraded {reason, needs}` pattern). Full surface tree applies (routes + snapshots + sweep + typegen). Update ch12's "honest limit" paragraph.
- **Q15 (driver seam):** seam = `_get_director()` (`routers/media_director.py:73-87`) never passes `drivers=` though `MediaDirector.__init__` accepts it (`media_director.py:610-637`). Add an env/settings-driven driver registry + `LocalFileMediaDriver` (kind e.g. `local_file`): play = write governed now-playing state under `data_path("media")`, real `status()`/`stop()`, `supports_duration`. Keep `media_reality` pack green; hermetic driver tests through the `present()` verify rail. Owner-driver doc section (how to register a Chromecast/etc. driver).
- **QA2 (presence target):** new explicit target form `"presence:auto"` resolved via the **H34.2 owner-presence store** (`routers/presence.py`, `autonomy/presence.py`) + `DeviceRegistry.resolve_room_default`. Do NOT bind to house-graph presence — `/api/house/state.presence` is structurally `[]` in production (GAP-9). Default-off behavior preserved: unknown/stale presence → honest refusal (`reason: presence_unknown`), never a guessed device. Never change existing `resolve_target` semantics.
- **Q1 (stream synthesis):** `_handle_input_stream` (orchestrator.py ~:1188) runs the first target agent and breaks — no `_synthesize`; `route_name` computed once for the primary and recorded for every agent (mislabels locality). Fan out per-agent (reuse `_call_agents_parallel` semantics), stream the synthesis (synthesize then stream its output, or stream primary + append synthesized merge — pick the design in the recon brief; preserve single-agent latency with a regression guard). Record per-agent route. Tests: multi-agent intent on the stream path produces synthesis; single-agent path byte-compatible.
- **Q6 (autonomy operability):** `AutonomyWorker._halted()` (~worker.py:142-152) checks only the `global` scope → honor per-agent scopes for that agent's tasks. Reaper: `running` tasks older than TTL (setting, default e.g. 1h) transition to `failed` with reason on tick. TDD both.
- **Q2 (notes parity):** the notes block injected on `/chat` (~web.py:774-780) is absent on `/chat/stream` (~:842-856) — inject identically; test.
- **Q5 (guardrails pair):** SEC-065 — `security.guardrails_mode` read once at boot (orchestrator ~:505-512) while posture reports the live setting; wire the 30s settings watcher to update the engine mode. SEC-071 — `content_preview` (audit.py ~:112) stores the raw first 100 chars even when findings exist; redact matched spans before persist. TDD both.
- **Stretch briefs:** QA4 — mediation ratio from IntentLog + kernel metrics, read-only route extension on `/api/metrics/kernel`; Q7 — parallel branch checks `[error:` prefix like serial (engine.py:85-104), delete keeps built-ins (workflows.py:173); Q8 — align promote keys to `prompt`/`expect_contains`; Q10 — widget → `Gateway.route` + `origin="inbound"` + taint; Q12 — DEMO chips on data.ts seeds + wire cockpit decision queue to the real queue or label demo; Q9 — email branch in `ChannelManager._SUPPORTED_SEND_CHANNELS` + dispatch via `EmailChannel.send`; Q14 — repro first, fix the actual cause; Q13 — read-route classification allowlist in `test_route_auth_matrix.py`.

## 7. Pitfall appendix (symptom → fix)

1. **Piped pytest lies** — a `| tail` makes the pipeline exit 0 on failures → always `> log 2>&1; echo exit=$?`, read the file.
2. **Shell cwd persists** — `npm --prefix` or explicit `cd /home/user/jarvis-hub &&`; a stray cwd makes `tests/` "not found".
3. **Stale HUD bundle** — any `frontend/src` change fails `hud-v2-build` until `npm run build` output (`agents/web/v2`) is committed in the same PR.
4. **OpenAPI drift from docstrings** — route handler docstrings feed `schema.gen.ts`; keep public docstrings stable (reviewer notes go in `#` comments) or regenerate typegen against :8765.
5. **Snapshot quartet** — route changes touch up to four gates: `route_auth.json` (hand-edit), `test_route_parity_guard.py --update`, `test_openapi_parity_guard.py --update`, `scripts/gen_api_sweep.py`; action kinds add `action_auth.json` + readiness `--update` + H27 counts.
6. **Ghost refs after squash-merge** — the remote branch auto-deletes; `--force-with-lease` then fails on stale info → `git fetch --prune` first; a plain push recreates the branch.
7. **Guard semantics** — `user_guard` passes bare localhost; `admin_guard` requires the token everywhere once one is configured → flipping a route to admin needs the HUD caller to send the admin header (check before flipping).
8. **status_sync JS counts** — `--reuse-js-counts` unless JS tests changed; the full run needs `npm ci` in both `frontend/` and `mobile/`.
9. **Reality-lane semantics** — `JARVIS_REALITY_HARNESS=1` un-skips live cases and owner-live probes fail honestly without opt-in → count assertions must be lane-aware.
10. **Never mass-format** — ruff-format nonconformance pre-exists repo-wide; `ruff check` only, on touched files.
11. **CodeQL gates the merge via a repository rule** — a fully green CI can still refuse to merge ("1 security relevant alert"; auto-merge just waits). The alert is named nowhere in CI logs — reason it out from the *scanned* diff (tests are paths-ignored per `.github/codeql/codeql-config.yml`). Exception text in an HTTP body (`str(exc)` in a response, #750) is `py/stack-trace-exposure` → constant `reason` strings only, specifics to the server log.
12. **Exact-shape pins live outside tests/ too** — the H28 operator pack pins the whole tick-summary dict inside `agents/core/observability/`. When adding keys to a shared summary/shape, sweep the WHOLE repo (`grep -rn '{"ran"' agents/ scripts/ tests/`), not tests/ alone (#754 retry 1).

## 8. Failure / stop protocol

- **PARK** (after 2 fix-push retries, infra flakes get one free re-run): convert PR to draft, retitle `[PARKED x2] …`, journal the exact failing command + last 20 log lines, leave the branch, advance. A parked PR still owns its files — later items route around them.
- **SKIP-OWNER** (before starting): item needs an owner decision/hardware/credentials → journal `SKIPPED-OWNER: <item> — <one-line question>` + the same line into the item's BACKLOG row in the next sync commit.
- **BLOCKED-OWNER mid-item:** ship the verifiable subset if it stands alone (honest partial, stated in the PR); else park with a paste-ready `docs/OWNER_TASKS.md` checklist line.
- **Hard stops:** main red for external causes (30-min diagnosis, then hold + report) · an auto-merged PR broke main (immediate revert PR; two reverts in one run = stop) · three parks · git/auth failure >20 min · toolchain/disk corruption.
- **Idle rule:** never wait idle >20 min.

## 9. Context-budget + journal protocol

- **Working journal** `<scratchpad>/run-journal.md`: append-only transitions + a STATE BLOCK rewritten at hour boundaries and before risky ops: `{clock, item, phase, branch, PRs+status, retries, next-3, cut-status, known-broken}`.
- **Committed ledger** = §3 status column + BACKLOG ticks + merged PRs — a fresh session reconstructs from these alone.
- **Post-compaction first action:** read the STATE BLOCK → `git status` → PR list. Reconstruct; never re-derive or re-plan.
- **Delegate to subagents:** bulk reads (>3 files), CI log digestion, manual-chapter lookups, repro hunts. **Never load:** `tests/_snapshots/*.json`, `schema.gen.ts`, the built bundle, BACKLOG.md whole (grep rows), full-suite logs (tail the file).

## 10. Reporting contract

- One journal line per state transition; hour-boundary paragraph: merged/open/parked/skipped counts + next action.
- Final report: the §3 table updated (merged SHA / parked / skipped-owner / cut) + the verification command and result per merged PR + suite counters + refreshed BACKLOG state + explicit close status per `docs/AGENT_WORKFLOW.md` (merged / auto-merge / waiting checks / draft-hold / blocked / superseded) + the next safe action.

## 11. Fresh-session boot checklist

1. `git config user.email noreply@anthropic.com && git config user.name Claude`
2. `git fetch --prune origin && git checkout -B <work-branch> origin/main` — confirm main's last commit is green before building on it.
3. Launch the baseline full suite in background (§5.5 command) — do not wait on it to start C1.
4. Write the journal skeleton (queue table + empty STATE BLOCK).
5. If mid-run recovery: reconstruct from §9 (state block → git status → PR list → §3 ledger) and resume the queue — never re-plan.
6. Read this doc's §6 brief for the current item; begin.

## 12. Beyond the run — the full finish sequence (for the owner)

- **Phase A (this run):** A8 unblockers + product holes + defect ledger (§3).
- **Phase B (next runs):** stretch lane to zero; SEC tail; NERVA_VISION §3/§4/§8 re-baseline (GAP-7/8); owner-enablement pack — a ≤10-min runbook + smoke check per PLUMBING→LIVE flip.
- **Phase C (owner, schedulable once A is merged):** A1 ⭐B0 re-run incl. ch15 ADV · A2 72h soak · A3–A5 settings/deps/license · A6 demo+landing · **A8 owner-host proof (now runnable)** · A7 design partners ≥2 weeks · A9 tag 1.0.0.
- The north star while executing: every merge must advance a gate or shrink the ledger without regressing the §6 counter-metrics (MOONSHOT "on track" definition).

---

## Appendix A — the 10-hour prompt

Paste this as the opening message of a Fable session on this repo (works mid-run too — rule 9 makes recovery deterministic):

```
You are Fable running a 10-hour continuous engineering shift on jarvis-hub (Nerva).
Mission: execute the run queue in docs/superpowers/plans/2026-08-01-finish-line-plan.md,
top to bottom, one item = one PR, driving each to a squash-merge on green CI. That plan
doc is the single source of truth for the queue, per-item briefs, acceptance criteria,
schedule, and protocols — read it FIRST, fully, before touching code. BACKLOG.md remains
the priority ledger; sync it in every PR per AGENTS.md.

Authority: you may implement, test, push, open PRs, enable auto-merge (squash), and
merge your own PRs when CI is green — pre-authorized for this run. You may NOT: flip
default-off flags on, attempt owner-lane items (A1–A9, GPU, license, GitHub settings,
hardware/credential config), change product defaults beyond an item's stated acceptance
criteria, or push to main directly.

Iron rules (violating any of these is failing the shift):
1. One item = one PR. TDD for every bugfix: failing regression FIRST, watch it fail.
2. Evidence over claims: every PR body carries the exact verification commands and their
   real results. Never report a suite green without the captured exit code
   (`> log 2>&1; echo exit=$?` — a piped pytest masks failures).
3. Run the plan doc's SURFACE DECISION TREE before every push (snapshot reseeds,
   gen_api_sweep, typegen, frontend bundle commit, PARITY row). "Green locally, red in
   CI" is almost always a skipped branch of that tree.
4. Sync-in-PR: status_sync counters + BACKLOG tick + test-manual annotation ride the
   same PR, as its last commit.
5. Pipeline only across disjoint files (serialized pairs: Q15→QA2, Q1→Q2). Never open
   PR N+1 before PR N merges.
6. Retry budget 2 per red PR (one free re-run for infra flakes), then PARK exactly as
   the protocol says and advance. Two consecutive parks → 30-min systemic diagnosis.
   An auto-merged PR breaking main → revert immediately; nothing merges until green.
7. Owner walls: skip-and-log before starting, or park with a paste-ready OWNER_TASKS
   line if discovered mid-item. Never wait on a human.
8. Time discipline: item caps S=60/M=100/L=160 min; even-hour checkpoints with the 60%
   cut rule; NO new PR after T+9:15; T+9:30 is fix-or-park for anything still red.
9. Journal: maintain the scratchpad run-journal STATE BLOCK at every hour boundary and
   before risky operations. After ANY context loss: read the state block, then
   git status, then the PR list — reconstruct, never re-derive or re-plan.
10. Never idle >20 min: CI windows are for the next item's subagent recon brief,
    journal upkeep, or stretch-lane S items.

Boot (in order): git config user.email noreply@anthropic.com && git config user.name
Claude → git fetch --prune && checkout the work branch from origin/main → confirm main
green → launch the baseline full suite in background to a log file → write the journal
skeleton with the queue table → read the plan doc's brief for C1 → start C1.

Reporting: one journal line per state transition; an honest one-paragraph report at each
hour boundary (merged/open/parked/skipped + next action); final report = the plan doc's
ledger table updated (merged SHA / parked / skipped-owner / cut, with the verification
command + result per merged PR) plus refreshed BACKLOG state. End the shift with every
branch pushed, no uncommitted work, and main green.
```
