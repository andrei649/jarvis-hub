# Migrate hermes-agent's best features into jarvis-hub (expert replication plan, v3)

## Context

Close the capability gap between **`hermes-agent`** (NousResearch, MIT, ~430k LOC,
local checkout `C:\Users\andrei649\Documents\GitHub\hermes-agent`) and
**`jarvis-hub`** (`C:\Users\andrei649\Documents\GitHub\jarvis-hub`, GitHub
`andrei649/jarvis-hub`) by porting hermes's genuinely differentiating mechanisms —
grounded in source-level reading of **both** codebases, not the month-old research doc.
BACKLOG ORIZONT 20 is marked 6/6 ✅ but several items are governed-surface stubs; the
*essence* of hermes (its per-turn learning loop) is absent from jarvis.

**What changed vs the previous plan draft (v2):** targeted verification found jarvis
already has the two integration seams v2 proposed to build —
`Orchestrator._complete_llm_turn()` ([orchestrator.py:1519](../../agents/core/orchestrator.py),
self-described *"single post-LLM seam: memory, checkpoint, logs, learning and trace"*)
and a bounded **`CoreMemory`** ("always-injected core facts (bounded ring)",
[cognition/memory.py:277](../../agents/core/cognition/memory.py)). Jarvis also already
*passively* encodes every turn into LivingMemory with surprise/novelty gating
(`_record_living_memory_after_turn`, orchestrator.py:1460). v3 therefore reframes
Phase 1 from "build subsystems" to "**add hermes's missing distiller into existing,
tested seams**" — and adds an explicit **skip list** for hermes features that are
anti-thesis for jarvis.

## Expert verdict — what hermes's value actually is

Having read both implementations: hermes's moat is **not** channel count or provider
count. It is the **closed per-turn learning loop**:

> After *every* turn, a tool-whitelisted background fork reviews the conversation and
> **autonomously** (a) distills durable facts into a *bounded, always-injected* memory
> core (`MEMORY.md`/`USER.md`, frozen-snapshot for cache stability) and (b) **creates or
> patches skills** (procedural memory). A weekly **curator** then manages skill lifecycle
> (active→stale→archived) from **usage telemetry** + **provenance**.

Jarvis has the *recording* half (LivingMemory encodes turns; DailyReflector extracts
nightly; `skill_drift.refine_proposal()` exists **wired only to tests** — verified) but
not the *reflecting* half. Everything else hermes offers is either infra breadth jarvis
partially has, or reach features that conflict with jarvis's local-first/governed thesis.

**Strategic frame:** jarvis's wedge is "the governed alternative." Porting the learning
loop **under jarvis governance** creates something neither project has: *a self-improving
agent whose self-modifications are quarantined, signed, and auditable.* That's the prize.

## Port / Adapt / Skip verdicts

| Hermes capability (source) | Verdict | Why |
|---|---|---|
| Per-turn background review fork (`agent/background_review.py`, `run_agent.py:_spawn_background_review`) | **PORT** ★ | The identity feature; jarvis has the seam ready |
| Bounded memory core + frozen snapshot (`tools/memory_tool.py` MemoryStore) | **ADAPT** | jarvis `CoreMemory` exists — extend & wire, don't rebuild |
| Skill self-improve + curator + usage/provenance/lifecycle (`agent/curator.py`, `tools/skill_usage.py`, `skill_provenance.py`) | **PORT** ★ | Wire existing `skill_drift.refine_proposal`; route patches through jarvis's quarantine/signing |
| Runtime context compression (`agent/context_compressor.py`, `context_engine.py`) | **ADAPT** | jarvis's 71-LOC compressor + injectable summarizer = wire auto-trigger + template |
| `IterationBudget` (`agent/iteration_budget.py`) | **PORT** | Tiny, valuable; jarvis has no iteration-depth control |
| execute_code file-RPC transport + env-scrub rules + resource caps (`tools/code_execution_tool.py`) | **ADAPT** | Extends jarvis `tool_rpc.py`/`sandbox.py`; enables remote backends |
| SSH terminal backend (`tools/environments/ssh.py`) | **ADAPT** | On-thesis: Pi 5 satellite node; aligns with node-mesh H12.17 |
| `SessionSource` + session keys + `DeliveryRouter` (`gateway/session.py`, `delivery.py`) | **PORT** | Load-bearing gateway abstraction; jarvis channels lack a session model |
| Cron tick + cross-process file lock (`cron/scheduler.py`; `msvcrt` path matters — jarvis is Windows-primary) | **ADAPT** | Builds on jarvis `autonomy/nl_schedule.py` + queue |
| `ProviderProfile` declarative provider plugins (`providers/base.py`) | **ADAPT (lite)** | Registry + capability flags behind existing `hybrid_router`; not 28 plugins |
| Delegation blocked-tools scoping (`tools/delegate_tool.py`) | **ADAPT** | Small hardening of existing `subagents.py` |
| **Modal / Daytona / Singularity serverless backends** | **SKIP** | Anti-thesis: jarvis is local-first on owned hardware (RTX 5090 + Pi 5); serverless cloud exec contradicts the privacy wedge |
| **Nous Tool Gateway** (`tools/managed_tool_gateway.py`) | **SKIP** | Routes searches/media through Nous-hosted vendor passthroughs — anti-privacy-thesis |
| **20+ channel breadth** | **DEFER** | Port the session *model* now; add WhatsApp/Signal (already tracked H12.16) only on demand |
| **Desktop app parity** (`apps/desktop/`, Electron) | **CUT** | jarvis 1.0 gate is productionizing + design partners; UI parity is post-1.0 |
| Hermes's architecture itself (16k-line `gateway/run.py`, `AIAgent` megaclass, sync threading) | **NEVER** | Port logic, not debt; jarvis's async + contextvars model is cleaner |

**Preserve where jarvis leads (regression = failure):** approval queue + risk gating,
Merkle audit, secret broker, encrypted secrets, signed skill marketplace + quarantine
(PENDING_REVIEW/CDX-8), dual-LLM quarantine (H17), bitemporal KG + RRF fusion. Every
ported mutating path routes through this governance.

## Architecture translation (single-agent → 17-agent orchestrator)

Design decisions resolved up front, so implementation doesn't stall:

1. **Who learns?** The review loop runs **once per completed turn at orchestrator level**
   (in `_complete_llm_turn`), not per-agent (never 17×). Skills are global (as today).
   The memory core is **one shared pair** — `CORE.md` (agent-learned facts, hermes
   MEMORY.md analog) + user profile (hermes USER.md analog, fed by the existing
   `memory/profile_extractor.py` / Howard pipeline) — injected into **every** agent's
   prompt after its persona `SOUL.md`.
2. **Two-tier learning cadence** (mirrors jarvis's fast/deep model tiering): **fast
   tier** = per-turn background review (small, bounded writes); **slow tier** = the
   existing nightly `DailyReflector` slot absorbs the **curator** (lifecycle transitions,
   consolidation, overlap merge). No second nightly system.
3. **Write governance tiers:** bounded-core *fact* writes = autonomous but
   injection-scanned (reuse jarvis's existing scanner/taint machinery, not hermes's) and
   user-visible/editable; `SKILL.md` *text* patches = autonomous **into quarantine**
   (existing PENDING_REVIEW + signing pipeline) with owner approval via existing UI;
   skill *code/scripts* = always quarantine. Hermes writes ungoverned — jarvis must not.
4. **Review model policy:** review sees raw conversation ⇒ **strict-local by default**
   (generalize the Frigga rule); runs on the **fast slot** with low `max_tokens`, sharing
   the KV prefix of the just-finished turn (same model + stable system prefix — cheap on
   llama.cpp/LM Studio too, not just Anthropic).
5. **Local-GPU cost policy** (hermes never had to solve this; jarvis does): configurable
   `learning.review_cadence` = `every_turn` | `idle_gap` (default: fire after N-second
   idle, coalescing rapid-fire messages) | `every_n_turns`; plus a daily review budget
   (pattern exists: autonomy interrupt budget). Review is fire-and-forget
   (`asyncio.create_task`), never blocks the interactive turn.

## Phased roadmap

### Phase 0 — Primitives (small)
- Port `IterationBudget` → `agents/core/iteration_budget.py`; wire into orchestrator's
  agent-call path + `subagents.py`. Add `DELEGATE_BLOCKED_TOOLS`-style scoping to
  `subagents.spawn()` (from `tools/delegate_tool.py:44`).
- No new turn hook needed — `_complete_llm_turn` (orchestrator.py:1519) is the seam.

### Phase 1 — The governed learning loop ★ (the migration's centerpiece)
**1a. Wire + extend the bounded core.** Verify `CoreMemory.system_prompt_block()`
(cognition/memory.py:316 renders `[core memory]`) is actually injected into
`agent.py:build_prompt()` — the H21.3 docstring says live wiring "is the integration
seam," so it may be unwired. Wire it; add the user-profile half (char-bounded, from
`profile_extractor`); adopt hermes's **frozen-snapshot discipline** (session-start
snapshot → prompt; mid-session writes → disk only) for prompt-prefix stability; scan
entries with jarvis's injection/taint scanner at snapshot time (hermes pattern:
`[BLOCKED: …]` placeholder, user-deletable).

**1b. Background review distiller.** New `agents/core/learning/background_review.py`:
port hermes's three prompts (`_MEMORY_REVIEW_PROMPT`, `_SKILL_REVIEW_PROMPT`,
`_COMBINED_REVIEW_PROMPT` — incl. the **anti-patterns**: never capture env-dependent
failures, negative tool claims, transient errors) and its preference ladder (update
loaded skill → update umbrella → add support file → create new). Implement as an async
task spawned from `_complete_llm_turn`, tool-whitelisted to {core-fact write, skill
propose/patch}, cadence + budget per the cost policy above, actions surfaced to the user
("Profile updated", "Skill 'x' patch proposed").

**1c. Skill lifecycle + curator.** Wire the existing `skill_drift.refine_proposal()`
into 1b (currently test-only — verified). New `agents/core/skills/usage.py`
(`.usage.json`: use/view/patch counts, timestamps, pinned, state),
`skills/provenance.py` (write-origin contextvar → mark agent-created; only agent-created
are curatable), lifecycle active→stale(30d)→archived(90d, to `.archive/`). Curator logic
(port `agent/curator.py` state machine: interval + min-idle + stale/archive thresholds,
`.curator_state`) runs inside the existing nightly reflector slot. Bundled / marketplace
/ pinned skills are never auto-touched.

**Verify:** golden-transcript evals (see safety net below); live multi-turn session shows
core file updating on disk + re-injecting next session; a user correction produces a
quarantined skill patch that appears in the approval queue; full offline suite stays green.

### Phase 2 — Context compression maturity
Wire auto-trigger (token threshold ~75% of context) into the turn path; supply
`ContextCompressor`'s injectable summarizer from the fast slot; port hermes's structured
summary template (Historical Task / Pending Asks / Remaining Work), protect-first-3 /
last-6, and iterative summary-merge across compressions; keep system prompt stable
(pairs with 1a's frozen snapshot — improves local TTFT via llama.cpp prefix cache).

### Phase 3 — execute_code breadth (governed)
Add hermes's **file-based RPC transport** (request/response JSON files + parent poll
thread — works uniformly for Docker and SSH) beside the local path in `tool_rpc.py`;
port env-scrub rules (`_scrub_child_env`: secret substrings, safe prefixes, **Windows
essential vars** — jarvis is Windows-primary) and resource caps (300s / 50 calls / 50KB
stdout); define an explicit sandbox tool allowlist on the existing gated registry. New
`agents/core/environments/{base,local,docker,ssh}.py` (port from `tools/environments/`,
including the CWD marker protocol). **No Modal/Daytona/Singularity.**

### Phase 4 — Provider registry (lite)
`agents/core/llm/providers/` with a declarative `ProviderProfile` dataclass (auth type,
base_url, capability flags like `supports_vision`, `fallback_models`, message-prep hooks
— from `providers/base.py:38`) + self-registration, kept **behind** `hybrid_router`.
Extend `/model` into a picker (live model list). Add 2–3 profiles (Anthropic, OpenAI-
compatible/custom, OpenRouter refactor). **No Tool Gateway.**

### Phase 5 — Gateway session model
Port `SessionSource` (+ `build_session_key`) and a `DeliveryRouter`
(origin/home-channel/explicit-target/local, silence detection, truncation) into
`agents/core/channels/`; add a `PlatformEntry`-style adapter registry and media cache
(reuse jarvis's `ssrf.py` for URL fetch protection). This unlocks per-session
interrupt/resume, thread-aware replies, and gives cron a delivery target. Channel
*breadth* stays deferred (H12.16).

### Phase 6 — Cron scheduler
Persistent 60s tick + **cross-process file lock** (`msvcrt` on Windows / `fcntl` POSIX,
from `cron/scheduler.py:24`) + sequential-vs-parallel job pools + per-job toolset
restrictions, layered on `autonomy/nl_schedule.py` + queue, delivering via Phase 5's
router.

*(Desktop parity: cut from this plan — revisit post-1.0.)*

## Learning-quality safety net (Phase 1 is a behavior change, not just code)

- **Eval harness:** golden transcripts → expected review actions (writes fact / patches
  skill / does nothing). Include *negative* cases (env failure, transient error → must
  NOT write). Run offline in CI like the existing contract tests.
- **Rollback anchors:** drift-manifest content hashes (already in `skill_drift.py`) +
  `.usage.json` + snapshot of a skill before any curator transition; quarantine is the
  undo point for patches; `CoreMemory.clear()`/forget path already exists for facts.
- **Pollution guards:** bounded size is the backstop (core can't grow unbounded); dedupe
  new facts against existing entries (reuse consolidation's Jaccard matcher); per-day
  write budget.

## Cross-cutting

- **Async-first:** port logic, not hermes's threading; use `asyncio.create_task` /
  `to_thread`; respect the existing `contextvars` session isolation.
- **MIT attribution:** `LICENSES/` + `THIRD_PARTY_LICENSES` entry ("Nous Research, MIT")
  for every ported file.
- **Docs honesty:** as each phase lands, update BACKLOG ORIZONT 20 / STATUS.md Known Gaps
  from "stub ✅" to accurate status (truth-in-docs, per H7.8).

## Sequencing & effort

**Recommended: Phase 0 → 1 first** (~2–3 weeks; self-contained, highest strategic value,
touches only the verified seams), then reassess. Phase 2 (~3–5 days) rides on Phase 1's
prompt work. Phases 3–6 (~1–2 weeks each) are independent of one another and can be
picked by need. Run jarvis's offline suite (~2,400 tests) after each phase; add offline
tests per convention (`tests/test_background_review_*.py`, `tests/test_core_injection_*.py`,
`tests/test_skill_lifecycle_*.py`).

## File map (port FROM hermes → land IN jarvis)

| Capability | FROM (hermes-agent) | IN (jarvis-hub) |
|---|---|---|
| Iteration budget | `agent/iteration_budget.py` | `agents/core/iteration_budget.py` (new) |
| Review prompts + fork pattern | `agent/background_review.py`, `run_agent.py:1419` | `agents/core/learning/background_review.py` (new) + `orchestrator.py:_complete_llm_turn` |
| Bounded core discipline | `tools/memory_tool.py` (MemoryStore, frozen snapshot) | wire/extend `cognition/memory.py:CoreMemory` + `agent.py:build_prompt` |
| Skill usage/provenance/lifecycle/curator | `tools/skill_usage.py`, `tools/skill_provenance.py`, `agent/curator.py` | `agents/core/skills/{usage,provenance,curator}.py` (new); wire `skill_drift.py`; extend `skills/loader.py` |
| Context compression | `agent/context_compressor.py`, `context_engine.py` | extend `agents/core/context_compressor.py` + turn path |
| execute_code transport/scrub/caps | `tools/code_execution_tool.py`, `tools/environments/*` | extend `tool_rpc.py`, `sandbox.py`; new `agents/core/environments/*` |
| Provider profiles | `providers/base.py` | new `agents/core/llm/providers/*` behind `hybrid_router.py` |
| Session model + delivery | `gateway/session.py`, `gateway/delivery.py`, `gateway/platform_registry.py` | extend `agents/core/channels/*` |
| Cron tick + lock | `cron/scheduler.py` | extend `agents/core/autonomy/*` |
