# ORIZONT 25 — M1→1.0 Execution Blueprint (Fable-5 snapshot, 2026-07-02)

> **Who this is for:** any AI session — any model tier, any vendor, mid-session handoff or cold
> start — executing the road from v0.11 to 1.0 **without deviating from the plan**. It captures the
> working method of the strongest sessions to date so a weaker model can follow it mechanically and
> a strong model can extend it safely.
>
> **How it relates to other docs:** [`BACKLOG.md → ORIZONT 25`](../../../BACKLOG.md) is the tracked
> item list (status lives THERE — tick it in the same PR as the work). The verified ground truth
> this plan stands on is [`docs/research/2026-07-02-fresh-eyes-backlog-reverification.md`](../../research/2026-07-02-fresh-eyes-backlog-reverification.md).
> Architecture navigation is [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md). When docs disagree,
> **BACKLOG wins** — fix the stale one in the same PR.
>
> **Every `file:line` below was verified against HEAD (`adc3894`) on 2026-07-02.** Line numbers are
> anchors, not gospel — see Protocol rule 2.

---

## §0 Execution protocol (non-negotiable, model-agnostic)

These ten rules are the distilled working method. They exist because every one of them, when
skipped, has produced a real defect in this repo's history. Follow them even when they feel slow.

1. **Verify before you claim.** Never mark an item ✅ (in BACKLOG, a PR body, or a reply) without
   direct evidence: a test you ran, or code you read at the seam. The repo's culture treats an
   unverified-✅ as the worst defect class — worse than the bug itself, because it hides.
2. **Seams drift — grep the symbol, not the line.** Every `file:line` here is a 2026-07-02 anchor.
   First `grep -n "<symbol>"` the file; if the symbol moved, follow it. If the symbol is *gone*,
   **STOP**: re-read the item's *Intent* paragraph and `ARCHITECTURE.md §3`, find where the intent
   now lives, and note the drift in your PR body. Never improvise a new architecture because an
   anchor failed.
3. **One item = one PR.** Feature branch → draft PR → merge to `main`. Rebase-first at session
   start (`git fetch origin && git rebase origin/main`). Never push to `main` directly. Respect
   other agents' draft PRs as file locks (`AGENTS.md`).
4. **Default-off, byte-identical.** A behavior change ships behind a `JARVIS_*` env flag or a
   `settings_db` key, OFF by default, with the default path byte-identical (the 0.34/0.37/0.46
   pattern). Anything mutating gets a kill-switch. Recovery paths (kill-switch *disengage*,
   loop-breaker *reset*) are **never** gated by the thing they recover — this is a hard invariant.
5. **The honesty contract.** No surface ever fabricates: an off-by-default feature's panel says
   "empty until `<FLAG>` is on"; a missing quote is `no_quote`, never a made-up price; a planner
   stage carries `generated:false`; `_sys_info` probes or says `unknown`. Any new surface must
   state its own OFF state. (Precedents: `market/analyze.py`, `creative/pipeline.py`,
   `_sys_info`, every HUD panel banner.)
6. **Tests are offline and injectable.** Fake backends/clients, no sockets
   (`pytest-socket` loopback-only guard is CI-enforced), `Orchestrator.__new__(Orchestrator)` +
   manual attrs instead of full init, `tests/test_<module>.py`, sys.path header per
   `ARCHITECTURE.md §7`. A route surface change re-seeds parity snapshots **in the same PR**:
   `python tests/test_route_parity_guard.py --update` (+ openapi + auth-matrix as prompted).
7. **BACKLOG sync in the same PR.** Tick the ORIZONT 25 status cell, refresh the test counter if
   you added tests, and fix any doc your change made stale. Do not open a separate docs-only PR
   for this.
8. **Uncertainty rule.** When two readings of an item both seem valid, choose the one that is
   *reversible and default-off*, implement that, and record the fork in the PR body ("chose A over
   B because…"). Never silently expand scope; never ask the void — the PR body is the channel.
9. **Honest terminal states.** If a step fails twice for unclear reasons, stop forcing it. Set the
   item's status to what is true (`draft-hold` / `blocked: <why>`) and say exactly what you ran and
   what happened. A red truth beats a green lie (see `AGENTS.md` → session close states).
10. **Never touch:** `LOCAL_ONLY_AGENTS` cloud paths (frigga/ultron/howard **fail closed**, no
    fallback — MOONSHOT §5.1); shipped migrations (append-only — `persistence/migrations.py`);
    snapshot files by hand (only via `--update`); another agent's draft-PR files; an agent's
    voice/tone without owner consent.

---

## §1 Architecture crib (60 seconds, then go read the real map)

- **One brain:** `agents/core/orchestrator.py:Orchestrator` — every turn flows
  `add_turn → skills.parse_command → detect_llm_control → router.classify → plugins → hybrid_router.select_backend → agents → synthesize → persist` (`ARCHITECTURE.md §2`).
- **HTTP = 45 routers** under `agents/core/routers/` (never add `@app.*` inline in `web.py`);
  guards from `routers/_deps.py`; new-route recipe in `ARCHITECTURE.md §8` + skill `jarvis-add-route`.
- **The kernel** (`agents/core/kernel/`) mediates every privileged action:
  `kernel.authorize(action, capability, budget) → GRANT/DENY/QUEUE`. All 11 action kinds are
  KERNEL-mediated (Gate-K complete); tokens are mandatory for `TOKEN_MANDATORY_KINDS`. Default-off
  behind `JARVIS_ACTION_KERNEL`.
- **Memory** = conversation (JSONL) + vector + graph + RRF fusion (`agents/core/memory/`); all
  retrieved memory enters prompts only through `security/rag_guard.wrap_memory` (CDX-7).
- **Cognition** (`agents/core/cognition/`) = the personality substrate: `PersonaModule`
  (persona.py:32), `Mood`/`Affect` (affect.py:16,40), `HonestyModule` + `SycophancyIndex`
  (honesty.py:96,152), `TurnContext` (turn_context.py:21), registered as the `cognition` facade in
  `orchestrator.py:184-186`. Souls: `agents/<id>/SOUL.md` (public template) +
  `SOUL.local.md` (gitignored personal overlay).
- **Tests:** `pytest -q` from repo root (~3,2xx offline); frontend `cd frontend && npm test` +
  `npx tsc --noEmit`; committed v2 bundle must match a fresh `vite build` (CI `hud-v2-build`).
- **Before any task:** run the `jarvis-load-context` skill; never load the raw repo (~2M tokens).

---

## §2 M1 — v0.12 "Substrate sealed" (finish Track K/V engineering)

### M1.1 K3 — unify budgets into the kernel `BudgetLedger` (M)

**Intent.** Today four budget systems coexist: the kernel's `BudgetLedger`
(`kernel/budget.py:28` — per-task tokens/wall-time/recursion, enforced at `kernel.authorize`),
the autonomy `InterruptBudget` (≤4 urgent pushes/day, `autonomy/worker.py:43`), mission step/time
caps (`autonomy/missions.py` — `max_steps`, `budget_status`), and payment caps
(`payments.py:120 _deny_reason` — per-payment/cumulative/expiry). MOONSHOT §5.4's "≤4/day" should
be enforced *in one place*. K3 = make `BudgetLedger` the single object the kernel consults, with
the three legacy systems either delegating to it or registered as named dimensions on it.

**Seams.** `kernel/budget.py:28` (`BudgetLedger`; its own docstring at :7-9 names this exact
unification as "a later K3 slice"), `kernel/binding.py:33` (`make_budget_ledger` — the config/env
factory), `autonomy/worker.py:43` (`InterruptBudget`; wired from the
`autonomy.interrupt_budget` setting in `orchestrator.py` ~:265), `payments.py:120`,
`autonomy/missions.py` (step budget), the token-accrual precedent `call_broker.py:252`.

**Approach.** (1) Add named-dimension support to `BudgetLedger` (e.g.
`interrupts/day`, `money.total`, `mission.steps`) with the same deny-with-reason contract the
existing dimensions have. (2) Make `InterruptBudget` a thin view over the ledger dimension
(keep its public API — `worker.py` callers and tests must not change). (3) Payments: do **not**
rewrite `PaymentBroker` — register its cumulative-cap check as a ledger dimension consulted *in
addition to* (not instead of) the broker's own admissibility gate; behaviour identical, but the
kernel can now see money pressure. (4) Handler-level token hooks: let a task handler report
`tokens_used` back to the ledger (executor already wraps dispatch — `autonomy/executor.py`).
All of it inert when no ledger is configured (existing `make_budget_ledger → None` contract).

**AC.** One `BudgetLedger` instance can answer "how many interrupts today / money spent / steps
taken" for a task family; `InterruptBudget` behaviour byte-identical (its existing tests green
unmodified); over-budget on any named dimension → kernel DENY with the dimension in the reason;
default (no ledger) byte-identical.

**Tests.** Extend `tests/test_kernel_budget.py` + `tests/test_kernel_budget_binding.py`; add
`tests/test_k3_budget_unification.py` (named dimensions, InterruptBudget-view parity, payment
dimension observes-but-doesn't-double-gate, handler token report).

**Do NOT:** change `PaymentBroker._deny_reason` semantics (its parity is pinned by
`tests/test_payments_contracts_parity.py`); gate the loop-breaker/kill-switch reset paths; make
the ledger required.

### M1.2 Action.origin threading per channel (M)

**Intent.** The kernel already escalates GRANT→QUEUE for actions with a declared untrusted
`origin` (`kernel/__init__.py:57` default `"generated"`; escalation clause :213-219). TASK-3
marked taint at *producers* (websearch/news/digest/parsers, PR #481) but deliberately skipped the
inbound-channel funnel because channel text is a bare string. The honest fix (per the kernel's own
design note: taint cannot survive an LLM turn) is **declared provenance**: any action whose
originating turn came from an inbound channel should carry `origin="inbound"`.

**Seams.** `channels/gateway.py:52` (`Gateway.route(text, channel, **kwargs)` — the single inbound
funnel: pairing → rate-limit → orchestrator), `orchestrator.py:609` (`channel_handler`), the
`Action` construction sites in the brokers (`autonomy/call_broker.py`, `social.py`,
`writeback.py` — grep `Action(` under `agents/core/`), `kernel/__init__.py:213-219`.

**Approach.** Thread a `origin` kwarg from `Gateway.route` → `channel_handler` → the turn context
(the `_active_session` ContextVar pattern from BUG-5 is the precedent for per-request state) → any
broker that builds an `Action` during that turn reads it (default stays `"generated"`). Web-HUD
turns stay `"generated"` (the operator is trusted); telegram/discord/email/webhook channels =
`"inbound"`.

**AC.** A task proposed from a Telegram message that policy would GRANT is escalated to QUEUE by
the kernel; the same task proposed from the HUD is GRANTed; default path (kernel off) byte-identical.

**Tests.** `tests/test_m12_origin_threading.py`: gateway→handler threading, ContextVar isolation
under two concurrent channel turns (mirror the BUG-5 concurrency test), broker Action carries
origin, kernel escalation end-to-end with the real policy.

**Do NOT:** mark the owner's own HUD/voice turns untrusted; try to propagate taint *through* the
LLM (explicitly rejected design — see the comment at `kernel/__init__.py:213-217`).

### M1.3 V3 — components/skills in the readiness matrix (M)

**Intent.** `tests/test_capability_readiness_matrix.py` gates only the statically-enumerable
plugin set (33 records). Components and skills need a booted fixture, so a silently-broken
component can't currently fail CI.

**Seams.** `observability/capability_registry.py:174` (`build_records(orch=None)` — already
accepts an orch), `tests/test_capability_readiness_matrix.py` (docstring names this exact
follow-up), `tests/_snapshots/capability_readiness.json` (33 `plugin:` records),
`conftest.py:make_app` (lightweight app fixture precedent).

**Approach.** Build a minimal orchestrator fixture (the `__new__` trick + `ComponentRegistry` with
its real registrations — see `orchestrator.py:184+`), pass it to `build_records`, extend the
snapshot with `component:`/`skill:` records, keep the same drift/fabricated-VERIFIED/unclassified-
SEAM checks, and keep the honest escape sets non-stale.

**AC.** A component silently failing to register (WIRED→SEAM) fails CI; snapshot regen documented
in the test header; plugin behaviour unchanged.

### M1.4 LIVE/SEED chip rollout (S, mechanical)

**Intent.** The per-panel honesty chip exists (`PanelChip`, `frontend/src/gap.tsx:28`) and is
wired into 5 panels; ~25 Console panels remain. Pure repetition of the shipped pattern.

**AC.** Every Console panel renders its chip; `npm test` + `tsc --noEmit` + fresh `vite build`
committed. **Do NOT** invent per-panel logic — reuse `PanelChip` exactly.

### M1.5 Q4 — voice-persona consent gate (S)

**Intent.** 0.28: voice cloning/persona playback has no consent record. Add a one-time,
persisted, owner-visible consent (settings key, default absent → TTS persona features degrade to
the default voice with the honest banner) checked at the TTS persona entry point.

**Seams.** `voice/tts.py` (`TTSEngine.speak` fallback chain), `cognition/persona.py:32`,
`settings_db.py:DEFAULTS` (+ recipe `ARCHITECTURE.md §8`). **AC:** no persona/cloned voice without
recorded consent; default voice unaffected; `tests/test_q4_voice_consent.py`.

---

## §3 M2 — v0.13 "Quality gates & type truth"

### M2.1 H23.17 — flow-level E2E: chat + voice (M)

**Intent.** `frontend/e2e/` proves boot/paint/a11y only. Add real user-flow specs: send a chat
message → SSE tokens render → stop button works; voice UI state machine (mock `getUserMedia`).

**Seams.** `frontend/e2e/hud.spec.ts` (harness + webServer pattern — boots the real `serve.py`),
`frontend/playwright.config.ts`, the chat flow in `frontend/src/app.tsx` (`runTurn`/`submit`),
`voice.ts:49` (status machine). Backend answers without an LLM (graceful-degraded reply,
H23.12) — assert on the degraded reply text, don't require a model.

**AC.** A broken chat stream or a dead stop button fails the e2e lane; specs run in `npm run e2e`.

### M2.2 Nightly soak + browser matrix (S–M)

**Intent.** `.github/workflows/e2e.yml` runs only on push/PR (verified: no `schedule:`);
Playwright has a single chromium project (`playwright.config.ts:31`). Add a `schedule:` cron
(nightly) that loops the e2e suite N times against one server boot (the cheap soak: assert no
memory-growth/route-5xx across iterations via `/metrics`, AUD-17), and add firefox + webkit +
one mobile-emulation project, non-blocking at first (the `reality.yml` scheduled-lane precedent).

**AC.** Nightly lane exists and reports; matrix runs 3 engines; PR path unchanged (stays fast).

### M2.3 AUD-16 — OpenAPI→TS typegen + CI diff gate (M)

**Intent.** Exactly 1 route declares `response_model=`; `frontend/src/api/types.ts` is
hand-written and says so in its own header. Generate types from the live `/openapi.json` and gate
drift in CI.

**Approach.** (1) Backfill `response_model=`/typed returns on the ~30 endpoints the HUD actually
calls (grep `apiGet<`/`apiPost` under `frontend/src/api/`). (2) CI step: boot the server the way
`e2e.yml` already does → `npx openapi-typescript http://127.0.0.1:<port>/openapi.json -o
frontend/src/api/schema.gen.ts` → fail on git diff. (3) Migrate `types.ts` consumers gradually —
do NOT big-bang.

**AC.** A backend response-shape change on a HUD-consumed route fails CI with a readable diff.

### M2.4 V4 — eval-regression as a scheduled blocking lane (M)

**Intent.** The compare machinery exists (`tests/test_h9_3b_dataset_regression.py`,
`observability/datasets.py:34 DatasetStore`) but no CI lane runs a real eval. Wire a scheduled
lane (nightly, `reality.yml` pattern) that runs `EvalRunner` (`observability/eval.py:52`) over the
stored datasets against a real local model **when the runner host has one** (`JARVIS_EVAL_LIVE=1`
gate), records scores, and fails on regression vs the stored baseline. Offline PR path unchanged.

**AC.** Nightly eval lane exists; a score regression turns the lane red; north-star guardrails
(`north_star.GUARDRAILS`) reported in the same job summary.

### M2.5 Q1 — companion golden-dialogue eval set (M) ⭐ the quality snapshot

**Intent.** This is where the "Fable-5 quality" of *being Jarvis* becomes a regression-testable
artifact instead of a vibe. Curate 40–60 golden dialogues (RO+EN) covering the §6.2 charter:
practical assistance, empathy without sycophancy, follow-up on remembered context,
persona-consistency (in-character but honest under sincere questioning), graceful refusal,
proactive-but-budgeted suggestions. Score with the existing LLM-judge machinery
(`observability/quality.py:59 QualityMonitor`, `cognition/honesty.py:96 SycophancyIndex` +
`:134 HonestyJudge`) against a per-dialogue rubric. Store as a versioned dataset
(`DatasetStore`) so M2.4's lane guards it forever.

**AC.** `eval/datasets/companion_v1` exists with rubric; the nightly lane scores it; the
sycophancy index and honesty-judge dimensions are part of the score; a future model/prompt change
that degrades companion quality turns the lane red.

**Do NOT:** put real personal data in the golden set (souls are templates — the same rule
applies here; synthetic personas only).

### M2.6 BUG-2b.3 — `useVoice` hook tests (S–M)

Mock `getUserMedia`/`MediaRecorder`/`AudioContext` in jsdom; drive the
off/idle/listening/transcribing/speaking/error machine (`voice.ts:49`). The `ttsStream` half is
already covered (`frontend/src/test/ttsStream.test.ts`).

---

## §4 M3 — v0.14 "Reach & proof"

### M3.1 Mobile: Action approval queue first (M), then Dashboard, Tasks

**Intent.** 9 surfaces trail browser (`mobile/PARITY.md:35-46`). The approval queue is the
north-star surface — approving Jarvis's proposed actions from the phone *is* the product.

**Seams.** Backend: `GET /autonomy/approvals` + `POST /autonomy/tasks/{id}/decision`
(`routers/autonomy.py:362,208`, both admin-guarded — the mobile client already persists a token,
`mobile/src/storage/settings.ts`). Client pattern: `mobile/src/api/client.ts` (retry/backoff) +
existing screens under `mobile/src/screens/`. Update the `PARITY.md` row in the same PR (AGENTS.md
bridge rule).

**AC.** Approve/reject a pending task from the phone; jest tests for the pure client logic
(`mobile/jest.config.js` precedent); PARITY row flipped.

### M3.2 Plugin-gated HUD modes — honest wiring (M)

Finance/Health/Knowledge/Family modes + Comms threads render seeds today. Wire each to its live
endpoint with the honest empty state when the plugin is unconfigured (the `live.ts` swap pattern +
`liveSourceState()`); never fake data. Closes TASK-2.

### M3.3 H23.22 — landing page + demo support (M, dev half)

Static, self-contained landing (no external calls — same discipline as the HUD) built from
`docs/marketing/` copy + `docs/BRAND_BOOK.md` tokens; demo-capture checklist from
`docs/marketing/TEASER_PACK.md` shot-list (0.52). Owner records the actual video (M4).

### M3.4 AUD-14 — config consolidation (M, pulled forward: debt is compounding)

161 `os.getenv` sites (was ~121 at audit), ≥3 truthy conventions (`web.py:47`,
`routers/oauth.py:157`, `orchestrator.py:389`), model names scattered, policy sets hardcoded
(`hybrid_router.py:84,114`). Build one `env_config` module (typed getters, one `truthy()`),
migrate mechanically file-by-file, derive agent-policy sets from `agents.yaml` **with the
code-enforced `LOCAL_ONLY_AGENTS` floor kept** (BUG-14 lesson — the registry must never be able to
pull a strict-local agent cloudward).

### M3.5 #169 — WorldView MCP write transport (M) → then fold K2 HMAC tokens

The HMAC capability-token format is done and pinned cross-language; zero runtime callers. Build
the JARVIS-side stdio MCP client call path (`mcp/client.py:MCPManager` — connect, mint scoped
token, invoke `watch_aoi`/`reconstruct_event`), gated through plugin-gate + kernel like every
external write. Folding the HMAC token in as a kernel `Capability` kind = the last K2 slice.

### M3.6 Q2 — persona-consistency rail (S–M)

Add a persona dimension to the live `QualityMonitor` (`observability/quality.py:59`): judge each
sampled reply against the active agent's SOUL voice (source: `soul_versioning.py` current
version), alert on drift like the existing quality-decline alert. Uses `PersonaModule` +
`in_character_directive()` (`cognition/honesty.py:88`) as the contract: in-character always,
honest-under-sincere-questioning always.

### M3.7 Q3 — caring follow-ups in the morning brief (S–M)

**Intent.** "Caring" as behavior: the brief should *follow up*, not just report. Extend
`build_morning_brief` (`autonomy/digest.py:28`) with a follow-ups block sourced from
`build_unified_digest` (`memory/timeline.py:41`): yesterday's failed/blocked tasks ("X failed —
want me to retry?"), facts flagged as open concerns, upcoming dates from the KG. Zero new capture;
pure recomposition of existing stores. Respects the interrupt budget (it rides the existing
morning-brief slot).

**AC.** Given a failed task yesterday + a stored "Andrei mentioned back pain" fact, the brief
contains both follow-ups with provenance; empty stores → no fabricated section.

---

## §5 M4 — v1.0-rc "Proof" (owner-led; overlaps M1–M3, start immediately)

Tracked in [`docs/OWNER_TASKS.md`](../../OWNER_TASKS.md) — this list only orders it:

1. **⭐B0** governed-autonomy run on the RTX box (`docs/MANUAL_TESTING.md` §0) + 72h unattended
   soak — *the* 1.0 gate; also unblocks TASK-4 P1 confirmations + CLN green-light.
2. Record decisions **AUD-0** (breadth→depth) + **H23.23** (single-user for 1.0) in BACKLOG.
3. GitHub-settings batch (~15 min): code-scanning toggle (#242), CQ-2 dismissals, CQ-3 paste,
   SEC-4 required checks.
4. License flip MIT→Apache-2.0 + `TRADEMARKS.md`.
5. Recruit 1–3 design partners; **north-star measured on a non-owner install for ≥2 weeks** —
   calendar-bound, hence "start immediately".
6. GPU-opportunistic: H13.3 (config-only), H22.4, then H12.14/TASK-1 (needs data export).
7. Tag **1.0.0** when MANUAL_TESTING signs off **and** ≥1 non-owner install has a week of
   accepted-actions data. Not before. (MOONSHOT §4 gate discipline.)

---

## §6 The quality charter — what "Fable-5-grade" means here

### §6.1 For sessions working on this repo

The §0 protocol is the *mechanics*; this is the *judgment* it encodes:

- **Evidence over eloquence.** A claim with a `file:line` or a test run beats any well-written
  paragraph. When you cannot verify, say "unverified" — it is a respected answer here.
- **Fresh eyes beat memory.** Statuses rot in both directions. Before building on a claimed-open
  item, spend five minutes disproving it (this blueprint exists because 8 rows were stale-pessimistic
  on the same day the plan was written).
- **Finish-the-partial beats start-the-greenfield.** Standing guidance since the 2026-06-21 audit;
  it is why the competitive-gap table went from ~48 gaps to a handful in six weeks.
- **The default path is sacred.** Byte-identical until the owner opts in. This single discipline
  is what lets 40 PRs/week land without destabilizing a running personal system.
- **Honesty compounds; theater compounds too.** Every honest empty-state, every `no_quote`, every
  narrated-real-result builds the trust the product sells. One faked surface poisons the well.
- **Leave the campsite mapped.** Your PR body is a message to a future session that has none of
  your context. Say what you chose, what you deferred, and where the next seam is.

### §6.2 For Jarvis the product — the companion charter

The goal (owner's words): *a friendly, caring, smartest AI-human compilation — assistant, friend,
actor, any personality — that discusses and resolves problems automatically.* The substrate for
all of it already exists; this charter defines the quality bar every persona/conversation change
is measured against (regression-guarded by **Q1**, monitored live by **Q2**):

1. **Caring is behavior, not adjectives.** Remember (memory + provenance via `rag_guard`), follow
   up (Q3 brief follow-ups), anticipate (watchers/observer), act reversibly while you sleep
   (night-shift), and *stop asking* once trust is earned (preference learning). Warm words with no
   follow-through fail the bar.
2. **Smart is honest.** Never fabricate a fact, price, or system state. "I don't know — here's
   how I'd find out" is a first-class answer. Sycophancy is a measured defect
   (`SycophancyIndex`, `pushback_reversal_rate` — cognition/honesty.py): agreeing with the owner
   against the evidence *lowers* the score.
3. **Personality is designed, and it's a promise.** Voice lives in `SOUL.md` (public template) —
   personal warmth in `SOUL.local.md` (never committed). An agent may fully inhabit a role
   (Jerome the DJ, Howard the twin — `in_character_directive()`), but drops the mask instantly
   for a sincere "am I talking to an AI / is this real?" and never deceives about capability or
   action taken. Tone changes require owner consent; persona drift is monitored (Q2).
4. **A friend respects your attention.** ≤4 interrupts/day is a *character trait*, not a rate
   limit: fewer, better decisions; silence when nothing matters; the brief — not notification
   spray — is the voice of proactivity.
5. **Problems get the loop, not vibes.** Diagnose → propose with a preview (dry-run H12.5) →
   act reversibly or queue for approval → verify against reality → report the *actual* outcome
   (the LLM-control "no theatre" precedent: narrate what really happened, always).
6. **Privacy is the friendship's foundation.** Family/health/identity stay with strict-local
   agents, fail closed. The moment "it knows me" becomes "it leaks me," everything above is void —
   this ranks above every other clause.

**How this charter stays real:** Q1 (golden dialogues, nightly-gated) + Q2 (live persona/quality
monitor) + the north-star counter-metrics (reject rate ↑ = trust eroding). If a proposed change
improves benchmarks but violates a clause here, the clause wins — escalate to the owner.

---

## §7 Sequencing & what NOT to start

```
M1 (substrate)  →  M2 (gates + Q1)  →  M3 (reach + Q2/Q3)  →  tag v0.12 / v0.13 / v0.14
M4 (owner proof) runs in PARALLEL from day one — it is the critical path.
```

Within a milestone items are independent (any order, any session). Across milestones, only these
edges matter: M2.4 before M2.5's gating bite; M3.5 before the final K2 HMAC fold; M2.3's server-in-CI
step reuses M2.1's boot pattern.

**Do not start** (Phase E / post-1.0, re-affirmed): 0.20 Vault · 0.48 video production ·
0.64/0.65 desktop overlay + capture reflex · 0.66 connector breadth · AUD-13/AUD-15 structural
refactors · multi-user. When tempted, re-read MOONSHOT §4: we do not skip gates, and breadth
before proof is the OpenClaw failure mode.
