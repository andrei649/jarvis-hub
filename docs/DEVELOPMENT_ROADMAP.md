# Nerva — Developer Instructions & Long-Range Development Roadmap

> For any developer (human or AI) joining jarvis-hub/Nerva: **Part I** is how to work here,
> **Part II** is what to build and in what order. Grounded against `main` @ `a2d9556`
> (2026-08-31, post-#990), with Part II re-swept entry-by-entry against the backlog-zero branch
> head — every DRA id below was checked against the code, not against the ledger
> (`tests/test_doc_reference_integrity.py` keeps the two in step).
> Canonical sources outrank this file: `AGENTS.md` (workflow law), `BACKLOG.md` (priority truth),
> `MOONSHOT.md` §5 (non-negotiables), `docs/ARCHITECTURE.md` (where code lives),
> `AI_SYSTEM_PROMPT.md` (condensed orientation). When this file disagrees with them, they win —
> fix this file in the same PR.

---

## Part I — Developer instructions

### 1. Orientation (first hour)

Read, in order — nothing else yet (the repo is ~2M tokens; never load it raw):

1. `CLAUDE.md` → `AGENTS.md` → `docs/ARCHITECTURE.md` (module index + request lifecycle)
2. `MOONSHOT.md` (§4 phase gates, §5 non-negotiables) → `STATUS.md` (live counters)
3. `BACKLOG.md` — header + the **Discovery-run completeness audit (DRA)** section + the section
   you'll touch. This file is the single source of priority truth.
4. `MAX.md` — the finishing protocol; the codename "Max" starts it. Even outside a Max run, its
   §3 picking order and §5 desirability gate are the house sequencing rules.
5. Task-specific bundles: `.claude/skills/jarvis-load-context/SKILL.md` and `docs/AI_CONTEXT.md`.

### 2. Environment setup

```bash
# Backend (Python 3.12; the project runs from source, never pip-installed)
pip install -r requirements-beta.txt      # runtime (locked: requirements-beta.lock)
pip install -r requirements-dev.txt       # test/lint tooling
python scripts/install_smoke.py           # fast real-boot smoke: fake local LLM, /readyz, one turn
python serve.py                           # FastAPI on http://127.0.0.1:8080

# Local LLM (optional for dev — the whole test suite is offline)
# LM Studio on :1234 (or Ollama); model auto-detected by LLMRouter.detect

# Frontend (from frontend/): npm install && npm run typecheck && npm test && npm run build
# Mobile   (from mobile/):   npx jest && npx tsc --noEmit
# Runtime loops without HTTP: make runtime-up / runtime-status / runtime-down
```

### 3. The working loop (every change, no exceptions)

1. **Safe start** — `git status`, current branch, overlapping open PRs (a draft PR is a
   visibility signal, not a lock; coordinate only on genuinely overlapping paths).
2. **Classify risk** `R0`–`R3` per the risk table in `docs/AGENT_WORKFLOW.md` (advisory since
   #981 — a convention, not a GitHub-enforced gate). It guides tests, review, and merge care. R3 (authority/security) requires separate
   builder/reviewer/integrator — never rule on your own R3 work.
3. **One reversible slice = one branch = one PR.** Record goal / non-goals / paths / risk /
   tests / rollback in the PR body (the template enforces the exact-head evidence receipt).
   Security or authority changes always ship separately.
4. **Test-first where it bites** — red → minimal fix → green. Tests live in
   `tests/test_<module>.py` with the sys.path header; offline (pytest-socket blocks
   non-loopback); fake backends; `Orchestrator.__new__(Orchestrator)` for unit seams.
5. **Respect the invariant surfaces:** new routes in `agents/core/routers/<domain>.py` (never
   inline `@app.*`), guards from `routers/_deps.py`; env parsing via `env_config.py` helpers;
   SQLite schema via append-only `_MIGRATIONS`; every mutating effect behind
   permission → typed contract → Action Kernel → audit; untrusted text through
   taint / `rag_guard`; blocking I/O off the event loop (`asyncio.to_thread`).
6. **Gate before push** — and note that **PR-blocking CI gates were removed by owner decision
   (#981; archive to restore them: #985/#986)**, so local validation is now *your* discipline,
   not the pipeline's:
   ```bash
   python -m pytest tests/<targeted>.py -q      # then the adjacent sweep
   ruff check .                                  # or python scripts/code_health.py
   python tests/test_route_parity_guard.py --update   # only if app.routes changed
   python scripts/status_sync.py                 # only if counters changed
   ```
   (`scripts/check_ai_workflow_policy.py` **and** the machine-readable policy it validated,
   `.github/ai-development-policy.json`, were both removed with the gates in #981 and are archived
   in `docs/restore/dev-gates-restore-2026-08-30.zip`. There is nothing left to read or run: risk
   tiering is now a convention documented in `docs/AGENT_WORKFLOW.md`.)
7. **Sync coupled surfaces in the same PR:** route/OpenAPI/auth snapshots, OpenAPI→TS typegen,
   `mobile/PARITY.md` or `docs/design/HUD_V2_REMAINING.md` for user-facing changes, and the
   **BACKLOG rule**: tick delivered items + refresh counters in the same PR that merges them.
8. **Report honestly.** A red test is reported red; an unrun suite is never "passing"; a
   degraded/mock capability carries its `_degraded {reason, needs}` stamp. The repo's recurring
   audit finding is "a gate that checks the shape of a claim rather than its substance" — do not
   add another instance.

### 4. Definition of done (per slice)

Code + tests green locally · conventions above held · coupled surfaces synced · BACKLOG updated ·
PR body carries the exact-head receipt · independent review where the risk tier demands it ·
rollback is one revert. "Merged but not program-accepted" (see B7/#918) is a failure state —
don't create more of them.

---

## Part II — The long development roadmap

### Sequencing principles (fixed, from MOONSHOT/MAX — not preferences)

1. **finish > polish > new** — complete a 🟡 PARTIAL before touching anything 🌱/⬜.
2. **The 1.0 proof track outranks capability work**; capability minors may interleave, but phase
   gates are never skipped.
3. **Reachability beats features**: the dominant confirmed defect class (DRA audit, 53 findings)
   is *built-but-unreachable* — shipped backends with no caller/UI. Wiring what exists comes
   before building anything new.
4. **Time-to-first-value outranks capability** (GAP-0: 24k visitors and demand exists, the first
   ten minutes fail; the "0 partners" premise is stale — A7 closed 2026-08-28). *Decided
   2026-09-01 (owner):* the first-value path is the one-step design-partner bootstrap (Gate-2 🚧1)
   plus the first-30-minutes fully-local zero-key loop (🚧4), measured as **activation rate**; the
   H23.30 public demo is sequenced after it, as reach.
5. Every phase has an **owner lane** running in parallel — never fake it, never block on it;
   reduce owner items to ready-to-sign packets in `docs/OWNER_TASKS.md`.

### Phase 0 — Onboard & baseline (days 1–2)

- Run Part I §2 end to end; full `pytest -q` once to know your machine's baseline.
- Read `docs/research/2026-08-29-discovery-run-audit.md` (the DRA write-up) and
  `docs/BACKLOG_DAILY_BRIEF.md`.
- Inventory open PRs and the DRA ledger in `BACKLOG.md`; note which DRA items already carry
  "Shipped <sha>" markers — the ledger moves daily.

### Phase 1 — Truth & queue hygiene (week 1) — small, high-leverage, zero risk

The backlog itself has confirmed-stale rows; executing a stale plan wastes every later phase.

- DRA-09: refresh the factually-false SEC-B4 row and the stale SEC-B5 row.
- DRA-11/12/13: mark the already-merged plan clusters (e-stop surface, honesty doc fixes) as
  do-not-rebuild in the plan artifacts; fix the one stale `PARITY.md` phrase.
- ~~DRA-49: fix the misleading kernel-test docstring~~ **done** — `tests/test_kernel_authorize.py`
  now points at the shipped K3 loop-breaker/budget and K4 syscall waves and their own test files
  instead of a deferred K3; DRA-46: correct `NERVA_VISION.md`'s now-false "never executes" claim;
  GAP-7/8: restate the Hermes verdict + re-baseline pillar percentages in `NERVA_VISION.md`
  (both still open — `NERVA_VISION.md` is untouched).
- DRA-48: ✅ done — the dead `agents/_system/` installer stub (and its `WEEK-1.md` sibling) are
  deleted; the repo's live installer is the root `install.sh` (guard: `tests/test_dead_installer_stub.py`).

### Phase 2 — Security & integrity tail (weeks 1–3) — before new surface area

- **SEC-B5 residual** (DRA-02): bind/reset the recall-taint mark explicitly around the HTTP
  recall route (`routers/memory_kg.py` → `MemorySearchTool`) instead of relying on incidental
  asyncio context isolation.
- **CI posture honesty** (DRA-16 ✅, ~~DRA-30~~ ✅, issue #242): both halves are closed. CodeQL —
  the "private repo" rationale and `continue-on-error` are gone from
  `.github/workflows/codeql.yml`, and the posture is now stated the same way everywhere:
  advisory, push-to-main + weekly, not a required check, red on analysis/upload failure
  (`tests/test_codeql_posture.py` pins it). DRA-30 — the required-checks story no longer
  contradicts itself across the doc surfaces (the fifth, `docs/test-manual/08-security-privacy.md`,
  stopped filing it under "could not verify"), and the re-gate packet is on the owner lane:
  `docs/OWNER_TASKS.md` names every check to drop and `docs/restore/README.md` keeps each removed
  gate as an independently restorable patch (`tests/test_degate_posture_docs.py` pins it).
  **Owner-side residual only:** the GitHub settings themselves are unobservable from the repo.
- ~~**Egress truth** (DRA-23)~~ ✅ — every LLM backend now dials through
  `agents/core/llm/egress.py::llm_async_client`, so the ledger the HUD and support bundle present
  as local-first proof records model traffic that leaves the box instead of missing it; the
  localhost control-plane pollers stay out on purpose (`tests/test_llm_egress_ledger.py`);
  ~~DRA-47~~ ✅ — the SSRF refusal count and the per-scanner finding counts are measured
  (`security/ssrf.py::blocked_requests`, `routers/security_hud.py`), reported as
  process-lifetime numbers rather than as a zero that reads like a measurement
  (`tests/test_security_status_is_measured.py`).
- **Audit-doc debt**: ~~DRA-50 (`require_component` deferred-never-built)~~ — shipped as a
  behaviour-exact sweep of 45 guards plus a structural test that stops the boilerplate regrowing;
  ~~DRA-51~~ ✅ — **three** (not two) non-store writers rewrote their file in place; the per-turn
  memory snapshot, the ingestion watcher state and the Oracle bridge session file now all go
  through `persistence.atomic_write_json` (tmp+replace, tmp removed on failure), pinned by
  `tests/test_atomic_json_writes.py`. The `cameras/frigate.py` request-path `getaddrinfo` was
  already fixed before this branch — `_resolve_pinned` runs the resolver through
  `asyncio.to_thread` (`frigate.py:236`), so it is off the event loop; that clause was stale.
- **SEC-B6 / #911 / #916 / B7-#918 acceptances**: drive the recorded post-merge HOLDs to an
  evidence-backed accept-or-revert — reviewer/owner lane, prepared by you. *Owner decisions
  2026-09-01:* SEC-B6 #896 — the #894 directive is amended: an evidence-backed independent
  post-merge review of the merged artifact on current `main` (every `INTENTIONALLY_OPEN_READS`
  row of `docs/security/SEC-B6-open-reads-evidence.md` against handler source +
  `tests/test_route_auth_matrix.py` re-run) suffices instead of re-landing identical bytes —
  **PASS/HOLD: pending**, ✅ only on PASS; #911 **RETAINED**, post-merge SEC-B8 security audit
  commissioned bound to merge 790a725 — **PASS/HOLD: pending**; #916 **RETAINED**, the existing
  exact-head receipt (PR #916 comment 5308830474, head a2438d8) recorded as its attestation;
  B7 #918 **RETAINED** under a bounded default-off owner exception, still not program-accepted
  (see Phase 6). None of the four is governance-complete on the retain decision alone.

### Phase 3 — The reachability wave (weeks 3–8) — the DRA headline

10 shipped, user-facing routes have **no client caller** (DRA-15/36 — the CI-enforced
`UNCALLED_BACKLOG` punch list in `tests/test_hud_v2_parity.py`; it held 79 before this wave, and
`tests/test_doc_reference_integrity.py` keeps this number honest). Of the 61 at the start of the
reachability sprint, 49 left because a panel now genuinely calls them and 1 was never uncalled at
all (`agents/web/*.html` was missing from the gate's client globs, so `brain.html` fetching
`/api/brain/summary` did not count). The 11 that remain are each annotated on their entry with why:
six are deliberate refusals (an agent-produced input, a route that swaps nothing, two dead by
construction, two duplicates of already-wired surfaces) and five are deliberately-open UI work.
A shrinking number is only good news when it shrinks for the right reason — an earlier pass of this
sprint moved six routes into `MACHINE_FACING` to get the gate green, and an adversarial review
caught that four of those reasons were false; they are back on the list. DRA-15 and DRA-36 both stay
open — the list is shorter, not empty. Work it as a series of small vertical slices, each
deleting entries from the punch list; prioritize by user value:

1. ~~DRA-17 — CDX-8 generated-skill **review/approve UI**~~ **done (this PR)** (the whole
   self-improvement loop is invisible without it).
2. DRA-27 — memory write/hygiene controls: ~~decay~~ **done**; consolidate still open and
   blocked on where its `existing` memory list comes from (see the BACKLOG row).
   ~~DRA-52 — review-queue → eval-dataset promotion~~ **done (#997)**.
3. ~~DRA-28 — workflow create/edit surface for the shipped AI Step Builder~~ **done** —
   `WorkflowBuilderPanel` (`frontend/src/gap.tsx`) creates and edits flows;
   ~~DRA-39 — `flow_api.build_flow` silently dropping `subflow`~~ **done** — the compiler passes
   `subflow` through and now raises at compile time when a `kind="subflow"` step has no config,
   instead of silently returning the previous ctx value at run time.
4. DRA-29 — multimodal *input*, **half done**: ~~the VLM describe caller~~ **done**
   (`VlmDescribePanel` posts to `/api/vlm/describe`), but `POST /api/media/generate` **still has
   no caller** — nothing under `frontend/src` (outside the generated schema) references it, so
   this row stays open; ~~DRA-37 — marketplace rollback control~~ **done** (the ⟲ control on the
   SKILLS MARKETPLACE list, which is where the rollback data actually lives);
   ~~DRA-38 — acquisition drive trigger beyond curl~~ **done** —
   `POST /api/acquisition/{request}/drive` is driven from the AcquisitionPanel.
5. ~~DRA-19 — construct `SignalGovernanceBridge` in production~~ **done (#992)**;
   ~~DRA-21 — feed `StockQuotesPlugin` into the market router~~ **done** — `live: true` fills the
   symbols the caller did not price from the keyless `stock-quotes` feed, caller quotes win, and
   an unpriceable symbol stays `no_quote` behind a provenance block;
   ~~DRA-41 — give `self_evolution.py` its production caller~~ **done** —
   `POST /api/learning/evolve` plus the weekly learning-loop cadence, proposals gated
   (approving one does not hot-swap a live prompt).
6. ~~DRA-53 — `notes_store.py` (504 lines, no adopter): adopt it behind a route or delete it~~
   **done (adopted)** — it backs the `/api/notes/docs/*` block-document routes
   (`agents/core/routers/notes.py`, `tests/test_notes_docs_routes.py`).
7. ~~DRA-06 — the ScreenReflex HUD overlay half~~ **done** — `POST /api/screen/reflex` is the
   capture-to-answer core's first product caller and `ScreenReflexPanel` feeds it real bytes
   (file, paste, `getDisplayMedia`). Deliberately **not** shipped and said so in the panel: the
   OS-level screen grab and the 0.64 global hotkey are host-gated.

### Phase 4 — Capability completion (weeks 6–12, overlaps Phase 3)

Real code, still AI-doable without owner hardware:

- ~~DRA-07/14 — the fail-closed malformed-`NERVA_PUBLIC_PROFILE` **boot guard**
  (`boot_guards.py:enforce_boot_posture`)~~ **done** — `assert_parseable_posture_flags` refuses to
  start on an unrecognized spelling of a parse-critical flag, from both documented entry points
  (`tests/test_public_profile_boot_guard.py`). **The second half is still open:** the
  `agents.public.yaml` roster overlay — no such file exists in the tree, so the public demo still
  has no explicit agent allowlist.
- ~~DRA-05/10 — the governed **OSINT enrichment plugin** scaffold (injectable client, consumes
  `suggest_pivots` output, taint-visible, write-back approval-gated)~~ **done** —
  `agents/core/plugins/osint_enrich.py` implements the `PivotLookupClient` seam with keyless
  resolvers only, off unless `JARVIS_OSINT_ENRICH` is set, and never lets an indicator become the
  request host (`tests/test_osint_enrich.py`). DRA-10 was folded into DRA-05 as a duplicate.
- DRA-08 — Hermes v3 live wiring, **one of three phases done**: ~~Phase 3 — sandbox file-RPC
  `execute_code` pull~~ **done** (`POST /sandbox/execute` with `tools: true` runs the script
  through `ToolRPCSandboxRuntime`, allowlist + approval still apply, and there is no silent
  ungoverned fallback — `tests/test_sandbox_tool_rpc_pipeline.py`). **Phases 5 and 6 stay open:**
  gateway session keys (`SessionSource`/`DeliveryRouter`) and the cron job store.
- GAP-1 residue — the `MediaDriver` injection point + implementation seam for
  `routers/media_director.py`; the acquisition **caller** (scheduled worker or admin action
  invoking `synthesize_and_propose`); the node-mesh transport (`node_transport_not_built`).
- Agent depth — `agents/vision` + `agents/argus` real implementation (persona-only today);
  wire Hestia's reads/proposals onto `agents/core/house/**`; H30.8 tail. *Refreshed 2026-09-01
  (no owner decision taken):* #287 already routes world-intelligence queries through
  `ArgusInterface` via `plugin_gatherer._signal_layer_answer`; the WorldView handoff's "deeper
  Argus agent-dispatch routing" is this Phase-4 `agents/argus` slice (BACKLOG ORIZONT 19,
  no dedicated BACKLOG row yet), still unscheduled.
- ~~DRA-24 — model cached-input token cost (Gemini context caching is live but costed at zero)~~
  **done** — every price row carries a third `cached` rate and the estimator bills cached input at
  it, so the saving is no longer over-reported (`tests/test_cost_estimator.py`);
  ~~DRA-25 — implement or un-advertise the MCP SSE transport~~ **done (un-advertised)** — `stdio`
  is the only transport the contract and the admin route accept (400 before anything is
  persisted), and `/connect` reports the real handshake result instead of a hardcoded
  `connected: true` (`tests/test_mcp_transport_honesty.py`).

### Phase 5 — Proof track → tag 1.0.0 (calendar-gated, runs alongside 3–4)

The gate (owner decision 2026-07-11): **proof track AND six pillars at their v1 bar.** Most
machine rows are green; what remains is evidence, not code:

- **A2 72h soak** — now automated (`.github/workflows/soak.yml` + `scripts/soak_report.py`);
  needs the owner box to actually run it; collect and file the evidence.
- **GAP-4 / DRA-45** — the Hermes head-to-head on the owner's machine: 10 tasks, publish the
  table including losses (~1 day, feeds S1/S2). ~~DRA-45's tracking gap (no finder, cluster or
  owner-lane entry owned this)~~ **closed** — the protocol is written and frozen,
  [`docs/HERMES_HEAD_TO_HEAD.md`](HERMES_HEAD_TO_HEAD.md) (pinned by
  `tests/test_hermes_head_to_head_protocol.py`), and it now has a row in `docs/OWNER_TASKS.md`.
  Status **NOT RUN**: the measurement itself is owner-gated behind the Hermes licence/CVE review.
  *Owner decision 2026-09-01:* the four Anthropic-terms productivity subtrees are out of scope
  (removed from the importer allowlist); a **static-only** fresh review is commissioned against
  the exact pinned artifact (v2026.8.3 / 3c27eb6) — **PASS/HOLD: pending**; pull-for-execution,
  install and execute stay **WITHHELD**, so the head-to-head still cannot run.
- **Live-eval owner run** — `companion_eval --live-gate` against the real local model (the
  release-gate owner row stays FAIL until run).
- **A7 design partners** — recruit 1–3, ≥2 weeks usage, north-star measured on real usage;
  the feedback/NPS loop and export tooling already ship.
- **H23.22** — owner-recorded demo video on the shipped landing page.
- Then: `python scripts/release_gate.py` all-green → manual-test/audit pass
  (`docs/MANUAL_TESTING.md`) → owner legal/brand (`docs/OWNER_TASKS.md`) → **tag 1.0.0**.

### Phase 6 — Nerva 2.0 program to acceptance (months 2–4)

Contract-first epics, every slice bounded, no new authority (Ultron/`nerva.action.v1` stays the
sole privileged-action authority):

- Close the retained-but-unaccepted evidence (E6 #860, E9 #861/#864) with fresh post-B2
  acceptance decisions; keep B2's live issue-ledger enforcement (#943) reconciled. *Owner decision
  2026-09-01:* three read-only post-merge integrator reviews authorized, in order E6 #860 →
  E9-authority #861 → E9-totals #864, each an agent role distinct from the original builder and
  each recording an explicit GO/HOLD bound to the **real merge commit** of that PR on `main` —
  **results: pending**; the owner's yes authorizes the reviews and is explicitly not dependency
  acceptance.
- E1 Cortex: from shadow/measured to the E1.2b owner-evidence gate (owner inputs 3–5 decided
  2026-09-01 — sampling rule, retention policy `owner-local-e1-2-v1`, one owner-local run
  permitted; inputs 1–2 and the run itself still pending); E6 Reflection and E9
  Research Lab from `BUILDING` to accepted.
- B3 Continuity Core (#731): the one named gap is **Jarvis's own Identity Manifest** — give it a
  destination issue and an acceptance test. *Decided 2026-09-01:* destination issue **#1008**
  (E4 identity-boundary lane, not Howard; #762 stays Howard-only; no authority change); the
  acceptance test is still owed. Same day: criterion 5 (observed/inferred/simulated) homed in
  E2 #760 observation provenance, criterion 6 (Frigga isolation) under RISKS.md PRIV-02, the
  evaluation suite on the E9.0 harness as `evaluation_only`, MEM-03's taint line into #761.
- B7 task-level mediation: ~~owner records retain/exception for #918 and ledgers reconcile~~
  *done 2026-09-01 — #918 RETAINED under a bounded default-off owner exception, ledgers
  reconciled;* B7 stays **not program-accepted** and E5 **Night Shift** / E8 stay blocked until
  #906 is provisioned or re-scoped by a separate owner decision; E8 Hermes provider needs its
  provider-specific E9 evidence, license/SBOM closure (static review commissioned 2026-09-01,
  pending; E8.1c stays EXECUTING ADAPTER BLOCKED), and the adoption-grade primary-source pass
  (one Tier A candidate at a time, per the Innovation Lab catalogue §5).

### Phase 7 — Post-1.0 horizons (month 4+)

- **H23.30 public web demo** on digitaholic.ro — spec approved 2026-09-01 (v1 as written; roster
  overlay R2, deploy slice R3) and two of the four owner calls landed the same day (hardened
  profile + empty grants on the public box, H23.23 ratified); still waits on the remaining two
  (container host, LLM provider/key); the code halves ship in Phase 4.
- **H23.23 option B** — per-user isolation, if design-partner demand triggers it (option A
  ratified 2026-09-01: single-user per install for 1.0).
- **WorldView scale proof — owner-infra, opportunistic** (rescoped 2026-09-01): the KEDA 50k msg/s
  load test, 10k concurrent WS clients, multi-AZ DR game-day and CDN/1M-point tiles are off the
  Nerva 1.x critical path; the H19.x rows keep their honest 🔨 "code delivered, scale unproven"
  status. The live-source hops (ADS-B/AIS/TLE egress + local Kafka via the worldview
  docker-compose) stay pickable/owner-runnable because they feed the rebuilt globe.
- **0.18 GPU minor** — Howard fine-tune (H12.14), speculative decoding (H13.3);
  ~~DRA-44 hardware benchmark & profiles (still content-free)~~ **done** — detection now feeds the
  VRAM budget (no more static 24GB assumption) and `GET /api/system/hardware` publishes a
  spec-based score in which an unprobed component scores zero rather than being credited
  (`agents/core/hardware.py`, `tests/test_hardware_profile.py`). The **throughput** table in
  `docs/HARDWARE_BENCHMARKS.md` is still `— to measure —`: that is DRA-62's measurement half and
  needs owner hardware; its docs half (no page may promise measured tokens/sec the table does not
  have) shipped and is pinned by `tests/test_hardware_benchmarks_claims.py`.
- **DRA-26** — the GitHub-backed path-prefix lease service is **still unbuilt** (nothing in
  `agents/` implements it), so the only honest lease state stays `none`. What did close is the
  finding's honesty half: `PARALLEL_WORKFLOW.md` §3 now names this backlog row and this phase
  instead of leaving "planned" as a dead end (`tests/test_doc_reference_integrity.py`).
- ORIZONT 34 Mission Control tail; distribution (signed installers, appliance path), the
  remaining Hermes-migration phases, and whatever the next fresh-eyes audit surfaces — schedule
  one such adversarial audit per quarter; they have out-performed every other bug source in this
  repo's history.

### Cadence & rhythm

- **Daily:** pick per the §Sequencing rules; one slice → one PR; update BACKLOG in the same PR.
- **Weekly:** re-read the DRA ledger + `docs/BACKLOG_DAILY_BRIEF.md`; re-verify any row you're
  about to build **against the code at HEAD**, never against your memory of the ledger — this one
  moves in waves, and the backlog-zero run closed dozens of DRA rows at once; refresh owner
  packets.
- **Per merge:** BACKLOG sync, counters via `status_sync.py`, close the loop on your own PRs
  (CI, review threads) before starting the next slice.
- **Quarterly:** adversarial audit + docs-vs-code accuracy pass; re-rank everything against
  MOONSHOT §6 north-star (weekly autonomous actions accepted per active user).
