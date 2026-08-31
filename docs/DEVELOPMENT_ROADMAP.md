# Nerva — Developer Instructions & Long-Range Development Roadmap

> For any developer (human or AI) joining jarvis-hub/Nerva: **Part I** is how to work here,
> **Part II** is what to build and in what order. Grounded against `main` @ `a2d9556`
> (2026-08-31, post-#990). Canonical sources outrank this file: `AGENTS.md` +
> `.github/ai-development-policy.json` (workflow law), `BACKLOG.md` (priority truth),
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
2. **Classify risk** `R0`–`R3` per `.github/ai-development-policy.json`. It determines tests,
   review, and merge controls. R3 (authority/security) requires separate
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
   (`scripts/check_ai_workflow_policy.py` was removed with the gates in #981; the
   machine-readable policy in `.github/ai-development-policy.json` still applies — you now
   verify conformance by reading it, not by running a checker.)
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
4. **Time-to-first-value outranks capability** (GAP-0: 24k visitors → 0 partners; demand exists,
   the first ten minutes fail).
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
- DRA-49: fix the misleading kernel-test docstring; DRA-46: correct `NERVA_VISION.md`'s
  now-false "never executes" claim; GAP-7/8: restate the Hermes verdict + re-baseline pillar
  percentages in `NERVA_VISION.md`.
- DRA-48: delete or implement the dead `agents/_system/install.sh` stub.

### Phase 2 — Security & integrity tail (weeks 1–3) — before new surface area

- **SEC-B5 residual** (DRA-02): bind/reset the recall-taint mark explicitly around the HTTP
  recall route (`routers/memory_kg.py` → `MemorySearchTool`) instead of relying on incidental
  asyncio context isolation.
- **CI posture honesty** (DRA-16, DRA-30, issue #242): the repo is public but CodeQL is
  permanently non-blocking under a "private repo" rationale, and the required-checks posture
  contradicts itself across four surfaces. With #981's de-gate decision recorded, make the
  *documented* posture match the *actual* one — and put the re-gate criteria in front of the
  owner as a packet.
- **Egress truth** (DRA-23): close the egress-ledger blind spot the HUD and support bundle
  present as local-first proof; DRA-47: make the SSRF blocked-request and per-scanner counters
  measured or labeled unmeasured.
- **Audit-doc debt**: DRA-50 (`require_component` deferred-never-built), DRA-51 (two JSON stores
  still writing non-atomically), plus the open `cameras/frigate.py` request-path `getaddrinfo`.
- **SEC-B6 / #911 / #916 / B7-#918 acceptances**: drive the recorded post-merge HOLDs to an
  evidence-backed accept-or-revert — reviewer/owner lane, prepared by you.

### Phase 3 — The reachability wave (weeks 3–8) — the DRA headline

~70 shipped, user-facing routes have **no client caller** (DRA-15/36 — the CI-enforced
`UNCALLED_BACKLOG` punch list in `tests/test_hud_v2_parity.py`). Work it as a series of small
vertical slices, each deleting entries from the punch list; prioritize by user value:

1. ~~DRA-17 — CDX-8 generated-skill **review/approve UI**~~ **done (this PR)** (the whole
   self-improvement loop is invisible without it).
2. DRA-27 — memory write/hygiene controls: ~~decay~~ **done**; consolidate still open and
   blocked on where its `existing` memory list comes from (see the BACKLOG row).
   ~~DRA-52 — review-queue → eval-dataset promotion~~ **done (#997)**.
3. DRA-28 — workflow create/edit surface for the shipped AI Step Builder; DRA-39 — fix
   `flow_api.build_flow` silently dropping `subflow` (a real compile bug, not just UI).
4. DRA-29 — multimodal *input* (VLM describe / media generate callers); DRA-37 — marketplace
   rollback control; DRA-38 — acquisition drive trigger beyond curl.
5. ~~DRA-19 — construct `SignalGovernanceBridge` in production~~ **done (#992)**; DRA-21 — feed
   `StockQuotesPlugin` into the market router; DRA-41 — give `self_evolution.py` its production caller.
6. DRA-53 — `notes_store.py` (504 lines, no adopter): adopt it behind a route or delete it.
7. DRA-06 — the ScreenReflex HUD overlay half.

### Phase 4 — Capability completion (weeks 6–12, overlaps Phase 3)

Real code, still AI-doable without owner hardware:

- DRA-07/14 — the fail-closed malformed-`NERVA_PUBLIC_PROFILE` **boot guard**
  (`boot_guards.py:enforce_boot_posture`) + the `agents.public.yaml` roster overlay (the two
  AI-doable halves of the P0 public demo).
- DRA-05/10 — the governed **OSINT enrichment plugin** scaffold (injectable client, consumes
  `suggest_pivots` output, taint-visible, write-back approval-gated).
- DRA-08 — Hermes v3 Phases 3/5/6 live wiring: sandbox file-RPC `execute_code` pull, gateway
  session keys (`SessionSource`/`DeliveryRouter`), cron job store.
- GAP-1 residue — the `MediaDriver` injection point + implementation seam for
  `routers/media_director.py`; the acquisition **caller** (scheduled worker or admin action
  invoking `synthesize_and_propose`); the node-mesh transport (`node_transport_not_built`).
- Agent depth — `agents/vision` + `agents/argus` real implementation (persona-only today);
  wire Hestia's reads/proposals onto `agents/core/house/**`; H30.8 tail.
- DRA-24 — model cached-input token cost (Gemini context caching is live but costed at zero);
  DRA-25 — implement or un-advertise the MCP SSE transport.

### Phase 5 — Proof track → tag 1.0.0 (calendar-gated, runs alongside 3–4)

The gate (owner decision 2026-07-11): **proof track AND six pillars at their v1 bar.** Most
machine rows are green; what remains is evidence, not code:

- **A2 72h soak** — now automated (`.github/workflows/soak.yml` + `scripts/soak_report.py`);
  needs the owner box to actually run it; collect and file the evidence.
- **GAP-4 / DRA-45** — the Hermes head-to-head on the owner's machine: 10 tasks, publish the
  table including losses (~1 day, feeds S1/S2).
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
  acceptance decisions; keep B2's live issue-ledger enforcement (#943) reconciled.
- E1 Cortex: from shadow/measured to the E1.2b owner-evidence gate; E6 Reflection and E9
  Research Lab from `BUILDING` to accepted.
- B3 Continuity Core (#731): the one named gap is **Jarvis's own Identity Manifest** — give it a
  destination issue and an acceptance test.
- B7 task-level mediation: owner records retain/exception for #918 and ledgers reconcile — only
  then E5 **Night Shift** unblocks; E8 Hermes provider needs its provider-specific E9 evidence,
  license/SBOM closure, and the adoption-grade primary-source pass (one Tier A candidate at a
  time, per the Innovation Lab catalogue §5).

### Phase 7 — Post-1.0 horizons (month 4+)

- **H23.30 public web demo** on digitaholic.ro — once the four owner calls land (host, LLM
  provider, hardened profile, H23.23 ratification); the code halves ship in Phase 4.
- **H23.23 option B** — per-user isolation, if design-partner demand triggers it.
- **0.18 GPU minor** — Howard fine-tune (H12.14), speculative decoding (H13.3); DRA-44 hardware
  benchmark & profiles (still content-free).
- **DRA-26** — the GitHub-backed path-prefix lease service (specced, machine-asserted, unbuilt);
  until then the only honest lease state stays `none`.
- ORIZONT 34 Mission Control tail; distribution (signed installers, appliance path), the
  remaining Hermes-migration phases, and whatever the next fresh-eyes audit surfaces — schedule
  one such adversarial audit per quarter; they have out-performed every other bug source in this
  repo's history.

### Cadence & rhythm

- **Daily:** pick per the §Sequencing rules; one slice → one PR; update BACKLOG in the same PR.
- **Weekly:** re-read the DRA ledger + `docs/BACKLOG_DAILY_BRIEF.md`; re-verify any row you're
  about to build against HEAD (this ledger moves daily — four DRA items shipped in the last two
  days alone); refresh owner packets.
- **Per merge:** BACKLOG sync, counters via `status_sync.py`, close the loop on your own PRs
  (CI, review threads) before starting the next slice.
- **Quarterly:** adversarial audit + docs-vs-code accuracy pass; re-rank everything against
  MOONSHOT §6 north-star (weekly autonomous actions accepted per active user).
