# ORIZONT 35 — Autonomous Contributor: governed self-patching of the engine (design proposal)

> **Status: PROPOSAL, not yet an agreed BACKLOG horizon.** Written in response to an owner request
> ("plan a Nerva 2.0 feature that lets Jarvis work autonomously on its own code for
> self-improvement"). This document does **not** add scope to `BACKLOG.md` — per `AGENTS.md`
> ("nu adăuga scope la sprintul activ fără acordul explicit al utilizatorului"), the ORIZONT 35
> BACKLOG section is added only once this direction is agreed. Nothing here implements anything;
> it is a design + reuse map, same register as the other `docs/superpowers/specs/*` documents.

## 0. A naming collision worth flagging up front

**"Nerva 2.0" is already the name of a separate, currently in-flight meta-program**
(`docs/nerva2/*`, epics E0–E12: Cortex, Atlas, Episodes, Synapse, Research Lab, Reflection, Night
Shift, …, tracked in issues #757–#773). It is deliberately formal — typed contracts, append-only
evidence graphs, hostile test matrices — and explicitly **not** about live runtime capability yet:
*"E0 completion proves planning/control consistency, not live runtime capability"*
(`docs/nerva2/E0_COMPLETION.md`). Its own reconciliation docs (`ROADMAP_RECONCILIATION.md`,
`DEPENDENCIES.md`) do not name "the agent edits its own source" anywhere — the closest epic, E8
Synapse, is explicitly scoped to skills/capabilities, and E5 "Night Shift autonomous work loop" is
currently `blocked` on four other epics plus an open program gate (`B7`, issue #818).

**Scoping decision made here (owner sign-off needed):** this proposal is written as a normal
`BACKLOG.md` horizon — **ORIZONT 35**, following the existing ORIZONT 1–34 numbering and the H32
delivery format — built entirely on substrate that is *already shipped*, not gated on E1–E9
finishing. It is designed so it could later register a capability manifest with E8 Synapse or feed
E5 Night Shift once those unblock, but does not wait on them. If the intent was instead to route
this through the formal Nerva-2.0 epic ceremony, this document should be redone against that
process — slower (each E-epic slice so far took a dedicated contract+schema+hostile-test PR before
any capability existed) but more consistent with that program's rigor.

## 1. Why

Nothing today reads `agents/core/**`, proposes a diff, and opens a PR against jarvis-hub itself:

- `agents/core/self_evolution.py` optimizes agent *prompts* only (reversible, `requires_approval`,
  never self-applies).
- `agents/core/autonomy/tech_scout.py` only files read-only informational findings — no executor,
  same "observations inform, decisions interrupt" posture as `observer.py`.
- `agents/core/acquisition/` (ORIZONT 32/H32) only ever produces new, isolated, **stdlib-only**
  sandboxed modules under the skill/package store (`generator.py:160 StrictLocalGenerator`'s
  `_ALLOWED_MODULES` allowlist forbids `eval`/`exec`/`open`/`socket`/`subprocess`-shaped code) — not
  a diff against an existing FastAPI/asyncio codebase.
- `agents/core/plugins/oracle_bridge.py` only pulls + tests commits *other* agents already pushed
  (`git pull --rebase` then `pytest tests/`); it never writes code, commits, or opens a PR.

This is a real gap against `NERVA_VISION.md` §4 pillar P6 ("Capability Evolution"), and it is also
exactly the shape of capability the project's own cautionary tale — OpenClaw, MOONSHOT.md §2 — got
catastrophically wrong by shipping without governance. The design below is scoped as tightly as the
blast radius demands: it reuses five already-shipped governance subsystems instead of inventing new
ones, and it is structurally incapable of merging its own code — not by convention, by construction.

## 2. What already exists (reuse, don't rebuild)

| Piece | File | Reuse for ORIZONT 35 |
|---|---|---|
| Per-turn tool-call loop (bounded iterations, tool-call cap, deadline, approval pause) | `agents/core/agent_runtime.py:56` `AgentToolRuntime` | Execution engine for the "write the patch" step. New ToolRPC handlers (file r/w, git, test-runner) still need to be written — none exist today. |
| Persistent, resumable, budgeted multi-step workspace | `agents/core/autonomy/missions.py:88,116` `Mission`/`MissionStore` | State container for one candidate → design → sandbox → gate → PR run, instead of a new bespoke store (0.32 Mission Workspaces already `done`). |
| Task queue + dispatch-by-kind | `agents/core/autonomy/queue.py`, `executor.py:24 TaskExecutor.register(prefix, handler)` | Register a new `self_patch` kind. This alone feeds `accepted_per_active_user`/`reject_rate`/`proposal_funnel` on the north-star dashboard (`observability/north_star.py`) with zero new metrics plumbing. |
| Risk tiers + ASK/NOTIFY/ACT + earned-autonomy ladder | `agents/core/autonomy/policy.py` `RiskTier`, `AutonomyPolicy.decide()`, `_apply_earned_autonomy():245` | Pin the action at `RiskTier.IRREVERSIBLE_OR_MONEY` (3). `_apply_earned_autonomy()` never touches tier 3 — "never auto-executes" is structural, not a setting that could quietly earn its way up. |
| Declarative gate for a high-risk action kind | `agents/core/automation_contracts.py` `ContractTemplate`, `contract_denial()` — already adopted by 10+ domains (payment, social, writeback, skill-install, …) | New `SELF_PATCH_CONTRACT`, mirroring `REPO_SYNC_CONTRACT` in `oracle_bridge.py:50-63` — the only code that already touches this actual git repo. |
| Privileged-action mediation | `agents/core/kernel/__init__.py:128 authorize()`, `registry.py ACTION_REGISTRY` | New action kind `repo.propose_change` — **must** be added to `ACTION_REGISTRY` or it silently escapes the action-auth CI proof; `docs/nerva2/RISKS.md` already names this exact blind spot (`channel.reply`, `skill.install` missed it before). |
| Approval queue / decision cards | `agents/core/autonomy/action_approvals.py:21 ActionApprovalQueue`, `dry_run.py`, `inbox.py` | Same sink every other `Verdict.QUEUE` action uses. Default the surface to the **web/admin HUD queue, not Telegram** — the Telegram approval callback doesn't verify `chat_id`/owner allowlist yet (a separately tracked gap); a code-approval flow should not inherit it. |
| "Don't touch this path without an explicit unlock" | `.github/workflows/park-guard.yml` + `scripts/park_guard.py` `PARK_POLICY` | Reuse directly for the frozen zone (§4.3) instead of a second denylist mechanism. The loop must never be the one writing the `unpark:` override. |
| Sandboxed execution | `agents/core/sandbox.py` (Docker, `--network none`, read-only + explicit rw allowlist), `acquisition/sandbox_profile.py` (digest-pinned, proven by the mandatory `sandbox-isolation` CI job) | The patch is written and tested inside one of these, never against the live server's checkout. |
| Capability lifecycle + promotion-only-by-proof | `agents/core/observability/capability_registry.py` (`MISSING→SEAM→WIRED→VERIFIED→GA`, `record_verification()` is the only promotion path) and its reality-harness siblings (`operator_reality.py`, `media_reality.py`, …) | Register `repo.propose_change` here too; promote only via a new hermetic `self_patch_reality.py` probe, same pattern as every other pillar. |
| Mechanical merge, once a human says "ready" | `.github/workflows/pr-auto-merge.yml` — hourly `gh pr merge --squash` on PRs GitHub already reports `mergeStateStatus==CLEAN`, drafts untouched | Jarvis never calls a merge API. It opens a **draft** PR; a human converting draft → ready-for-review *is* the approval act; the existing workflow performs the mechanical merge once CI is green. |
| Understanding its own source before proposing a change | `agents/core/codeintel/index.py` (AST symbol index, "0.31 Code Intelligence") | Cheap reuse for the design step instead of grepping blind. |

## 3. The gap, stated precisely

Restating §1 as a single sentence: every existing "self-improvement" mechanism in this repo either
(a) only observes/reports, (b) only touches agent *prompts*, or (c) only produces new, isolated,
stdlib-only modules. None of them proposes a change to the engine's own source tree. ORIZONT 35 is
that missing piece, and only that piece — it does not replace or widen any of (a)–(c).

## 4. Design

### 4.1 The loop (one Mission per candidate)

```
select candidate  →  design doc  →  sandboxed patch + local tests  →  verification gate
   (read-only)        (read-only)      (isolated worktree/Docker)      (full CI-equivalent)
                                                                              │
        ┌─────────────────────────────────────────────────────────────────┘
        ▼
SELF_PATCH_CONTRACT + kernel.authorize(repo.propose_change)  →  Verdict.QUEUE (always, by construction)
        │
        ▼
owner approves in the existing approval queue  →  push branch + open DRAFT PR  →  human reviews
        │
        ▼
human marks "ready for review" (= the actual merge approval)  →  existing pr-auto-merge.yml merges on green CI
```

- **Agent/persona:** `steve` — already `claude`-policy-routed per `hybrid_router.py` (CTO & Builds is
  the natural owner; `tech_scout.py` defaults to the same agent for the same reason).
- **Candidate source:** an unblocked, small (`S ≤ 3`) `BACKLOG.md` item, an `error_logger.py`
  diagnostic, or a `code_health.py` finding — never a free-text prompt from chat. Bounded scope
  matters here specifically because `docs/nerva2/RISKS.md` names **AUTO-01** ("autonomous work
  invents scope beyond an approved goal") as an open risk; a curated candidate source is the
  mitigation.
- **Coding step:** `AgentToolRuntime` driving Steve's Claude backend, with a new, narrow ToolRPC
  toolset — file read/write scoped to one throwaway git worktree, `git add`/`commit`, run
  `pytest`/`ruff`, nothing else. The loop harness and the sandbox are reused; this toolset is new.

### 4.2 Governance — cited against this repo's own stop-ship list

MOONSHOT.md §5.7 and `docs/nerva2/RISKS.md`'s stop-ship invariants apply directly:

- *Ultron/kernel is the sole privileged-action authority — no scheduler or agent self-authorizes.*
  Every path here ends at `kernel.authorize`; nothing grants itself an outcome.
- *[An evaluator] cannot rewrite source evidence or approve its own lesson* (RISKS.md invariant 5,
  stated for Reflection/E6) — applied here: the loop that writes the patch is never the thing that
  approves or merges it. The approval queue and the human PR review are two different trust
  boundaries, not one.
- *Every autonomous loop needs an approved scope/budget/deadline/stop-condition/loop-breaker*
  (invariant 6) — bounded candidate source (§4.1) + a hard weekly proposal cap
  (`autonomy.self_patch_max_per_week`) + the kernel's existing `BudgetLedger`/`LoopDetector` (K3) +
  the per-task wall-time budget already in `TaskExecutor`.
- *Every completion claim needs environment-appropriate verification evidence* (invariant 7) — §4.4
  and §6; a patch failing any gate is discarded, never proposed, and logged as a rejected attempt.
- Named **open** risks this must not worsen: **AUTO-01** (scope invention, mitigated by curated
  candidates, above) and **AUTO-05** ("irreversible action with no independent verification/
  rollback" — mitigated because the entire output of a run is a closable draft PR until a human
  merges; nothing is irreversible before that point).

### 4.3 Frozen zone

The loop must never propose a diff touching: `agents/core/kernel/**`, `agents/core/security/**`,
`agents/core/automation_contracts.py`, `agents/core/autonomy/policy.py`, its own module(s),
`.github/workflows/**`, `scripts/park_guard.py` itself, and packaging/release scripts. Reuse
`PARK_POLICY` (`scripts/park_guard.py`) rather than a bespoke denylist — it already has CI wiring
(`park-guard.yml`) and a precedent (`unpark: <module>` override). The loop must never be capable of
writing that override itself; a self-patch PR touching a parked path fails closed, no self-service
unlock.

### 4.4 Risk tier & kernel wiring

- `repo.propose_change` is classified `RiskTier.IRREVERSIBLE_OR_MONEY` (tier 3) — the most
  conservative tier available, even though a draft PR is technically reversible, because this
  action touches the trust boundary itself. `_apply_earned_autonomy()` structurally never promotes
  tier 3 past ASK; loosening this later requires a human-authored code change, not earned trust.
- New `SELF_PATCH_CONTRACT` in `automation_contracts.py`: constraints on diff size, frozen-zone
  cleanliness, tests-green, branch-name pattern, candidate provenance (must reference a real
  BACKLOG id or diagnostic id).
- `repo.propose_change` **must** be registered in `agents/core/kernel/registry.py`'s
  `ACTION_REGISTRY` — see §2 row on privileged-action mediation.

## 5. Phased delivery (mirrors the H32.1–H32.7 pattern — one PR per phase, red→green tests each time)

| # | Phase | Ships | Risk |
|---|---|---|---|
| H35.1 | Candidate selection (read-only) | Picks one bounded candidate from BACKLOG/diagnostics/code_health; no code touched | zero |
| H35.2 | Design-doc generation (read-only) | Steve/Claude produces the AGENTS.md-style goal/non-goals/files/risk/tests/rollback doc for the candidate; persisted as an artifact for manual owner review | zero — first owner-visible checkpoint, before any code exists |
| H35.3 | Sandboxed implementation | New ToolRPC handlers + throwaway worktree/Docker; Steve writes+commits a patch on a scratch branch; frozen-zone check enforced at the RPC layer, not just prompted | contained by sandbox network-none + rw allowlist |
| H35.4 | Verification gate | Full pytest + ruff + bandit + code_health + route-parity/OpenAPI snapshots, run inside the sandbox; any failure discards the patch (never proposed) and logs a rejected attempt | none — pure gate |
| H35.5 | Contract + kernel + approval | `SELF_PATCH_CONTRACT` eval → `kernel.authorize(repo.propose_change)` → `Verdict.QUEUE` → lands in the existing web/admin approval queue | this is the trust boundary; everything above is inert until owner approval |
| H35.6 | Draft PR on approval | Minimal, narrowly-scoped GitHub-write helper pushes the branch + opens a **draft** PR (design doc in the body); human review + draft→ready is the merge approval; existing `pr-auto-merge.yml` does the mechanical merge on green CI | PR-only; no push to `main`, no merge call anywhere in Jarvis |
| H35.7 | Audit + telemetry + HUD | Hash-chained audit entries per stage; outcome tracking (proposed/approved/rejected/merged/reverted) feeding a per-capability confidence stat; extend the existing self-improvement router/HUD surface with a card for this | none |
| H35.8 | Hermetic eval (Hermes-parity style, mirrors H32.7) | Offline CI lane with a fake coding backend proving the full loop end-to-end, plus negatives: frozen-zone violation rejected, failing tests never proposed, budget cap enforced, no live GitHub calls in CI | promotes `repo.propose_change` from SEAM→VERIFIED in the capability registry |

H35.1+H35.2 alone are genuinely zero-risk (no git writes at all) and are the recommended starting
slice — they let candidate-selection quality get checked against real BACKLOG items before any
code-writing capability exists.

## 6. Files touched / new modules (indicative, not exhaustive)

- `agents/core/autonomy/self_patch.py` — candidate selection + mission-kind orchestration logic
- `agents/core/autonomy/missions.py` — reuse `Mission`/`MissionStore` as the state container (no new store)
- new ToolRPC handler module — scoped file/git RPC tools, sandbox-bound
- `agents/core/automation_contracts.py` — `SELF_PATCH_CONTRACT`
- `agents/core/kernel/registry.py` — register `repo.propose_change` in `ACTION_REGISTRY`
- `agents/core/observability/self_patch_reality.py` — new hermetic probe (mirrors `operator_reality.py`)
- `agents/core/routers/self_improvement.py` — extend `self_improvement_status()` with a `self_patch` summary key
- `scripts/park_guard.py` — extend `PARK_POLICY` with the frozen zone (§4.3)
- new, narrowly-scoped GitHub-write helper (branch push + draft PR only — explicitly not widening
  `oracle_bridge.py`'s scope beyond read+test, to keep that file's trust boundary unchanged)
- `tests/test_self_patch_*.py` — new suite, fake coding backend, red→green per phase
- `BACKLOG.md` — new `## 🤖 ORIZONT 35 — Autonomous Contributor` section, added once this direction
  is agreed (see §0); `STATUS.md` synced in the same PR per AGENTS.md convention

Optional, cheap, on-brand first step: file this as an `OBSERVATION`/`IDEA` in the Innovation Lab
ledger (`docs/nerva2/KNOWLEDGE_GARDEN_V1.json`, per `INNOVATION_LAB_RFC_V1.md`) — doc-only, zero
runtime risk, and it is literally what that ledger exists for ("preserve ideas... without allowing
research to become delivery silently").

## 7. Non-goals

- No auto-merge, at any confidence level, ever — merge stays a GitHub-native human action.
- No editing the frozen zone (§4.3) — not "ask first," structurally refused.
- No bypassing any existing CI gate (ruff/pytest/bandit/semgrep/gitleaks/sandbox-isolation/route-parity/OpenAPI).
- Not a general coding-agent-for-hire — candidates only from BACKLOG/diagnostics, never a free-text
  chat prompt (that capability already exists as Claude Code itself).
- Does not touch or depend on the Nerva-2.0 E0–E12 program's files or gates (§0).
- Default OFF (`autonomy.self_patch_enabled=false`), hard weekly proposal cap even when on.

## 8. Verification plan

1. **Static:** ruff/bandit/code_health clean on all new files.
2. **Offline unit tests:** `tests/test_self_patch_*.py` with a fake coding backend (the
   `FakeBackend(LLMBackend)` convention used throughout this suite) — red→green per phase, per
   AGENTS.md's TDD convention. Route-parity/OpenAPI/route-auth snapshots re-seeded if
   `self_improvement.py` gains routes.
3. **Manual dry run:** enable only H35.1+H35.2 against real BACKLOG items; read the generated design
   docs; confirm candidate selection is sane before H35.3 exists at all.
4. **Hermetic reality pack (H35.8):** the fake-backend CI lane above; the artifact that promotes the
   capability in `capability_registry.py`, same as every other pillar.
5. **Supervised live trial:** turn the full loop on against exactly one tiny, real, low-risk backlog
   item; verify the draft PR's quality and design doc; approve or reject through the real queue;
   confirm audit trail + outcome telemetry are correct; separately, deliberately feed it a
   frozen-zone-violating candidate and confirm it is refused before any PR is opened.
6. Full offline suite (~6,341 tests) stays green throughout.

---

## 9. Appendix — unconstrained-resources framing (optional; owner flagged this half as a stretch goal)

"Top self-building AI project" already has a scoreboard in this repo: `NERVA_VISION.md` §8 defines
S1–S8, a measured (not asserted) superiority bar against Hermes Agent — the most credible public
comparison. With unconstrained budget, the highest-leverage moves:

1. **Turn ORIZONT 35 into a fleet, not a single loop.** Parallel sandboxed Steve workers picking off
   BACKLOG items continuously, coordinated the same way the existing multi-CLI dev-swarm already is
   (`lock.py`, draft-PR-as-lock, the "conductor agent" pattern in `AGENTS.md`) — visible live in
   Mission Control (H34, `/mission-control`). The bottleneck stays the human merge queue, on purpose
   — that is the governance floor, not a scaling limit to remove.
2. **Fund E9 Research Lab into a real continuous SWE-bench-style harness for this repo** (extends
   `reality_harness.py` / the H32.7 hermetic-Docker-CI pattern) that scores every self-patch
   proposal over time — reuse rate, acceptance rate, regression rate — and publishes the dashboard.
   Evidence beats claims everywhere else in this codebase; this capability should not be an
   exception.
3. **Unblock the formal Nerva-2.0 program on purpose** — dedicated engineering on E1–E3/E6/B7 so E5
   Night Shift and E8 Synapse actually reach `VERIFIED`, the mechanism (NERVA_VISION §7) by which any
   capability, including this one, could legitimately earn autonomy beyond "ask" — through evidence,
   not by loosening a guardrail.
4. **Externalize the proof.** The project's real edge over Hermes/OpenClaw-style rivals is governance
   rigor it has not yet spent on external validation (S5–S8: kernel-mediated everything, tamper-evident
   audit chain, local-first, the house/media/capability moat). Publish the audit-chain + reality-harness
   methodology; submit the operator/self-patch loop to independent public agentic-coding benchmarks.
   Capability parity is catchable by anyone; a public, verifiable governance story is not.
5. **Keep §4.2's non-negotiables exactly as they are at any budget.** The thesis that separates this
   project from the cautionary tale it explicitly names (MOONSHOT.md §2, OpenClaw) is "most capable
   *under* governance," not "most autonomous." More money should buy more verification and more
   parallelism, never a shortcut past the kernel.
