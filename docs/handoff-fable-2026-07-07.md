# Handoff — Fable 5 last-day review (2026-07-07)

> Written by Claude (Fable 5) on its final session with this repo. Purpose: leave the
> project in a state where **any** successor — owner, Claude, opencode, Gemini, Codex —
> can pick the next task without re-deriving strategy. This is a *review + ordered
> to-do*, not new scope. When this doc disagrees with `BACKLOG.md`, BACKLOG wins
> (per `AGENTS.md`); fix the stale one. The task lanes below are mirrored as tick-able
> tables in **BACKLOG.md → "🤝 Handoff — Fable last-day review (2026-07-07)"** — tick
> both places.

---

## 1. Ground truth verified today

- **CI on `main` is fully green** (2026-07-07 morning): CI, Security, CodeQL, HUD E2E,
  Smoke Test, Eval Nightly — all `success`. **Zero open PRs.** Clean handoff state.
- **Local offline suite:** re-run in a fresh Linux container this session (Python
  3.11) — **3,820 tests collected, suite green, exit 0**. STATUS.md re-synced via
  `scripts/status_sync.py` in this PR.
- **Doc drift found & fixed in this PR:** the test counter said ~3,727 (BACKLOG.md),
  ~3,806 (STATUS.md) and ~3,480 (docs/ARCHITECTURE.md) simultaneously. Only STATUS.md
  is auto-synced; the other two were hand-bumped and stale. All three now match.
- **Install bug found & fixed in this PR:** `requirements-beta.txt` pinned
  `numpy>=2.5.0`, which only exists for Python ≥3.12 — on a 3.11 box the *entire*
  install fails (despite numpy being commented "optional"). Now split with an
  environment marker; 3.12 behavior unchanged. Relevant because design partners
  (Phase 5 / M4) will not all have your exact box.

## 2. The verdict (unchanged, sharpened)

The engineering is **done enough**. v0.11 is feature-complete, refactored, contract-
gated, taint-tracked, eval-harnessed, with 45 routers, 17 agents, and a green offline
suite. The year-one review already said the true sentence — *"shipping more horizons
will not close a single product gap"* — and the repo has kept shipping horizons anyway
(~50 commits merged to `main` in the last week alone, essentially all inward-facing).

**The binding constraint is no longer code. It is proof.** Every remaining item that
matters for 1.0 is in the owner lane: the ⭐B0 manual run, the 72h soak, design
partners, real north-star data. An AI session cannot do these. What an AI session *can*
do is (a) not add scope, (b) keep the truth-in-docs discipline, and (c) clear the small
engineering tail listed in §4 — in that order.

**If you read one instruction: run ⭐B0 on the RTX box this week.** Everything else
below is sequenced around that.

## 3. Lane A — Owner critical path (ordered; nothing here is delegable)

Mirrors `docs/OWNER_TASKS.md` + BACKLOG M4/Phase 5 — consolidated and ordered:

1. **⭐B0 governed-autonomy demo + `docs/MANUAL_TESTING.md` full pass** on the RTX
   5090 box. This *is* the audit gate; no tag ships without it.
2. **72h soak** (0.63) right after B0 — same hardware, unattended, zero trust
   violations. Record **AUD-0** and **H23.23** (two one-paragraph decisions).
3. **Dependabot re-triage** — ✅ **agent half done in this PR** (gate challenged
   2026-07-07: `npm audit`/`pip-audit` enumerate the alerts locally, no UI paste
   needed). Fixed: frontend `undici` high (dev-chain) + worldview/mcp `hono` high
   ×5 advisories + `esbuild` — both trees now 0 vulnerabilities, suites green.
   Your tail: worldview's 2 moderates (postcss bundled *inside* next — re-run
   `npm audit` when next 16.3 ships), the mobile Expo SDK upgrade on a real
   device (gate *proven*: a non-forced bump broke `tsc` in the audio path), and
   dismissing the stale alerts in the GitHub UI after merge.
4. **GitHub settings batch** (~15 min total): repo description/topics/social preview
   (BRAND_BOOK §9) · enable code scanning or unrequire the CodeQL check · dismiss the
   7 triaged FP alerts (CQ-2) · paste the remaining ~12 CodeQL alerts to an agent
   (CQ-3) · promote route-parity/auth-matrix to required checks (SEC-4/F-10).
5. **License flip** MIT → Apache-2.0 — 🟢 **fully prepared in this PR**:
   `TRADEMARKS.md` live, CONTRIBUTING relicense grant in place (before any partner
   contribution lands), canonical Apache-2.0 staged in `docs/legal/`. The flip is
   3 owner commands (exact steps in OWNER_TASKS); timing per LICENSE_DECISION =
   just before v1.0. Only the sign-off is yours.
6. **Demo video (60s) + publish the landing page** — dev half is done
   (`marketing/landing/index.html` + `demo-shot-list.md`); the recording is yours.
7. **Recruit 1–3 design partners** and run the north-star on a non-owner install
   ≥2 weeks (calendar-bound — start recruiting *before* the soak finishes).
8. **Tag 1.0.0** only when MANUAL_TESTING signs off *and* real-usage data exists.
9. *GPU-opportunistic, next time at the box:* H13.3 speculative decoding
   (config-only) · H22.4 `OLLAMA_NUM_PARALLEL` · H12.14/TASK-1 Howard first real run ·
   LM Studio `lms` end-to-end · live-mic/barge-in tuning · mobile Expo SDK upgrade
   (11 audit moderates, needs a real device).

## 4. Lane B — Engineering tail (any AI session; one item = one PR, default-off)

Ordered by leverage. The ORIZONT 25 protocol digest (BACKLOG) stays in force:
rebase-first, verify-before-claim, byte-identical default path, honest empty states.

1. **Hermes migration v3 — reviewed, verdict below (§5).** ✅ **Phase 2 delivered in
   this PR** (context compression maturity: `keep_first`, structured template,
   iterative summary-merge, opt-in strict-local summarizer — defaults byte-identical,
   +12 tests). Remaining: Phase 3 live wiring (file-RPC transport for Docker/SSH —
   primitives merged in #628/#630/#631, and #632's `ToolRPCSandboxRuntime` is tested
   but has zero production callers yet), Phase 5 live wiring (gateway session/delivery
   model into `Gateway.route` — primitives in #626), Phase 6 cron tick + file lock —
   all **on-demand only** (§5). Keep the skip-list sacred (no Modal/Daytona, no Tool
   Gateway).
2. **0.19 First-Run Command Center** — ✅ **delivered in this PR** (owner go-ahead
   2026-07-07): `GET /api/onboarding/command-center` + the HUD `CommandCenterPanel`
   (new Start Console cluster) — install health, model truth, wizard state, and
   honest first actions in one read; "say hello" drives a real `/chat` turn.
   Mobile catch-up tracked as **H18.19** (PARITY.md row added).
3. **AUD-14 tail** — ✅ re-audited in this PR: zero unsafe parses remain (no typed
   `int()`/`float()`/`json.loads()` on raw env, no ad-hoc boolean truthiness; the
   ratchet test is green). The ~104 remaining plain string reads are cosmetic —
   migrate opportunistically in files you already touch, don't sweep.
4. **M2.4 live-eval lane** — ✅ **ci-small-model lane shipped in this PR** (owner
   go-ahead): `companion_eval --live-model` + the opt-in `live-small-model` nightly
   job (repo var `JARVIS_EVAL_CI_SMALL_MODEL=1` activates it — flip it to start the
   advisory trend lane). The owner-box fidelity lane (`JARVIS_EVAL_LIVE`) stays
   separate and owner-gated.
5. **Non-v0 inbox channels** — ✅ **email half shipped in this PR** (owner
   go-ahead): inbound email → inbox threads with SMTP reply metadata, contract
   branch, pairing-gated senders — all against test doubles; your live SMTP/IMAP
   round-trip validates it. WhatsApp stays parked (bridge hardware).
6. **Maintenance runbook** (`REVIEW_YEAR_ONE` §9.7) — ✅ **drafted in this PR**:
   [`docs/MAINTENANCE_RUNBOOK.md`](MAINTENANCE_RUNBOOK.md). Bus factor 1 is the top
   risk in the risk register and the cheapest to mitigate. Owner: correct the
   `[owner: verify]` marks (box-specific facts I couldn't check), then delete them.
7. **Doc-counter hygiene** — `scripts/status_sync.py --check` in CI is deliberately
   non-blocking, but BACKLOG.md and ARCHITECTURE.md counters are hand-maintained.
   When touching them, sync all three (they had three different values today).

## 5. Hermes v3 plan review (STATUS listed this as "pending Fable review" — done)

**Verdict: APPROVED with notes.** The plan is honest, source-verified, and correctly
reframed (v3's "wire into existing seams, don't rebuild" is right — `_complete_llm_turn`
and `CoreMemory` were confirmed real seams, and Phase 0–1 has in fact already merged
cleanly through them). Notes for whoever executes the tail:

- **The centerpiece already shipped.** Phase 0–1 (per-turn governed learning loop) is
  on `main`, default-OFF behind `cognition.enabled` + `cognition.review_enabled`, with
  the strict-local fail-closed fix (`LLMRouter.local_backend`) from the adversarial
  review. Do not re-implement; extend.
- **Phase 2 next, and small.** Context compression rides on Phase 1's frozen-snapshot
  prompt work; it's ~3–5 days and improves local TTFT — the one remaining phase with
  direct daily-use value. Do it before 3/5/6.
- **Phases 3/5/6 are "on demand", not "next".** Their primitives are merged and
  tested; live wiring should wait for a concrete need (a Pi 5 satellite, a real
  remote-exec use case, a cron consumer). Wiring them now is scope-gravity —
  exactly what §2 warns against. Park them behind actual pull.
- **Guard the two invariants in every phase:** (1) review model strict-local by
  construction (never `HybridRouter.backend`); (2) every self-modification lands in
  quarantine/approval, never direct. These are the wedge — a self-improving agent
  whose self-modifications are governed. Regression here is thesis failure.
- **Turn on the loop for yourself now** (`product.posture=companion_wave1`). It's
  merged, tested, and OFF. The north-star needs it *experienced*, not just shipped —
  and you are design partner #0.

## 5b. Gate challenge (2026-07-07, owner-requested): every "gated" label re-tested

Each gate was attacked, not assumed. Results:

| Gate | Verdict after testing | Autonomous path found |
|------|----------------------|----------------------|
| A3 Dependabot | **BROKEN** — local `npm audit`/`pip-audit` = same data as the UI | Fixed the 2 fixable highs in this PR; only UI dismissals + upstream waits remain |
| Mobile Expo moderates | **CONFIRMED by experiment** — non-forced bump broke `tsc` (expo-audio `AudioPlayer.addListener`); reverted | None headless; needs SDK upgrade + device |
| A5 license flip | **HALF-OPEN** — the *decision* is already recorded (`docs/LICENSE_DECISION.md`, 2026-06-04); only sign-off is owner's | An agent can prepare the full Apache-2.0 + TRADEMARKS.md diff on request; owner just merges |
| B4 live-eval runner | **HALF-OPEN** — "live model" needn't mean *your* model | Proposal: CI live lane against a small OSS model (e.g. Qwen-0.5B via llama.cpp) on GitHub runners — real LLM-judged lane, semantics honestly labeled `ci-small-model`; the owner-box lane stays for fidelity |
| B5 email inbox transport | **HALF-OPEN** — "send seam unproven" applies to *live* delivery, not the code | Proposal: implement email transport v0 against local SMTP/IMAP test doubles (aiosmtpd), default-off; owner's live validation flips it on. WhatsApp stays fully gated (bridge hardware) |
| B7 Hermes 3/5/6 | **CONFIRMED** — no consumer exists (no Pi 5 / remote target / cron job unserved by SchedulerService); wiring now = attack surface with no gate progress | None until a real consumer appears |
| A1/A2 ⭐B0 + soak | **CONFIRMED** — the human gate is the point (MANUAL_TESTING is *your* sign-off) | Agent can pre-run the automatable runbook steps headlessly to shorten your session |
| A4 GitHub settings | **CONFIRMED** — repo settings/branch protection have no agent-accessible API here | None |
| A6/A7/A8, GPU items | **CONFIRMED** — recording, recruiting, tagging, hardware | Support materials only |

Doc-staleness sweep ran alongside (same PR): MOONSHOT's current-stage line said
v0.10.0 (→ v0.11.0), AGENTS.md still framed `web.py` as a live god-object with 255
inline routes (fixed in #296 — reworded to past tense), ARCHITECTURE.md said
"304-route surface" twice (now points at STATUS.md's synced live count), JARVIS.md
said ~299 routes (→ live-count pointer). Counter drift is systemic: prefer pointing
at `scripts/status_sync.py`-synced STATUS.md over hand-written numbers in prose.

## 6. What NOT to do (reaffirmed non-goals until 1.0)

0.20 Vault · 0.48 video pipelines · 0.64/0.65 desktop overlay · 0.66 connector
breadth · multi-user · AUD-15 strict-TS sweep · any new horizon. The park-list CI
guard (Phase 6, ORIZONT 26) exists for a reason. MOONSHOT §4: gates are not skipped —
and per §2 above, *the backlog is a comfortable place to hide from users*.

## 7. Risk register (concentrated, from REVIEW_YEAR_ONE §10 — still all live)

1. **Bus factor 1** — 70K+ LOC, two stacks, one person. Mitigation exists as a task
   (§4.6) but not as a document. Highest severity, least discussed.
2. **Scope-gravity** — ~50 inward-facing merges/week while the owner lane sits
   untouched is this risk *materializing*, not a hypothetical.
3. **Safe but not useful** — governance is proven; value-per-accepted-action is not.
   Only B0 + partners can falsify this.
4. **The thesis survives the compiler but not the user** — n=1 until Phase 5 runs.

---

*Closing, from the departing model: the machine is ready. The next 90 days are decided
by whether B0 runs on the box and whether a stranger installs this. Nothing an AI
merges this month changes either. Point it at a user.*
