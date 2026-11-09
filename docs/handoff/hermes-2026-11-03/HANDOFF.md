# Handoff — Hermes batch 3 (2026-11-03), for the next developer (Codex)

> Historical batch-3 receipt. Resume current work from the
> [canonical Hermes execution workflow](../../hermes/autonomous-development-objective.md)
> and [cumulative handoff](../../hermes/CAMPAIGN_HANDOFF.md), checking the actual
> branch and SHA. Later owner directions supersede this document's old counters,
> next-task list and publication steps; the current campaign is local only.

Owner instruction (2026-11-03): development moves to Codex; this file is the handover.
Branch: **`claude/hermes-batch3`** (draft PR "Hermes batch 3"). `main` is at `68b351f6` (#1335).
Ledger source of truth: `docs/hermes/assessment.json`. Query it, never load it raw:
`scripts/hermes_status.py summary|list|show|check|write`, `scripts/hermes_restamp.py drift|cite|stamp`.
BACKLOG: query with `scripts/backlog.py counts|open|show|sections|find` (the file is ~1 MB).

## Where things stand

- **On `main` (merged this week):** #1331 batch 1 (H019, H422, H026, H339 equivalent; H462 partial),
  #1332 batch 2 (H448, H255, H430 equivalent; H381, H325 partial), #1333 CHANGELOG, #1334 audit
  close lock, #1335 schema.gen.ts regeneration. Ledger on `main`: **141/697** equivalent.
- **On this branch, code complete and tested:** five rows, each built in its own worktree and
  looped through fresh adversarial review until the reviewer found nothing left; then merged
  together and reviewed again as one branch (see "Integration review" below).

| Row | What it is now |
|---|---|
| **H330** | A skill delete can share a batch with edits to other skills and name `absorbed_into`; other skills' `related_skills` and bundle members migrate to it; every other holder (prose, jobs, load set, switches, pending proposals/batches) is reported under `references`. Every write of skill bytes crosses the new `skill.generation` kernel kind; a delete crosses `skill.install`. (`agents/core/skills/references.py`, `skills/batch.py`, `skills/tools.py`, HUD `panels/skill-batches.tsx`) |
| **H389** | When the tool loop prunes an old `skill_view` copy it leaves a `[SKILL_PRUNED]` marker; the reload notice and the system-prompt notice follow the loop's own fence decision (vetted copy = instructions to follow again, fenced copy = data). Bounded/spilled pages are pruned too. (`skills/tools.py`, `tool_rpc.py`, `tool_result_store.py`, `agent_runtime.py`) |
| **H058** | Per-command access tiers: the owner runs everything, everyone else `/help` + `/whoami` plus what `commands.user_allowed_commands` allows per channel and DM/group (fails closed). Denials are audited (`slash_command_denied`) on the cold, busy, quick and `/btw` paths of every channel and the web door. Reset triggers are owner tier and can never be a floor command. (`agents/core/slash_access.py`, `docs/FLAGS.md`) |
| **H202** | The owner's agent roster: create (template or blank), rename, retire (nothing deleted), restore — admin routes, `nerva agents`, HUD dialogs beside the SOUL editor; crosses `admin.agent_roster`. Retired agents leave the agent list, routing and room labels. (`agents/core/agent_roster.py`, `routers/agents_api.py`, `frontend/src/agent-roster.tsx`) |
| **H046** | The learning journey: every TODAY entry has an id; learned notes, profile facts, skills and stored facts can be listed, shown, edited and forgotten (`/api/dashboard/today/entries*`, `nerva journey` with aliases `learning`/`memory-graph`, HUD TODAY card), writes cross `kg.write`. A skill is dated by when it was learned or changed, never by a use. |

### Integration review (after the merge)

A fresh four-lens review of the merged branch (18 agents, each finding re-checked by a skeptic)
found real cross-row defects; all are fixed with tests that fail on the old code
(`tests/test_h330_h046_integration.py`, `tests/test_agent_roster_routes.py` last two tests,
`frontend/src/test/today-panel-journey.test.tsx`):

- the journey's skill archive dropped H330's `references` report (bundles and `related_skills`
  kept naming a gone skill, silently) — now returned and shown in CLI and HUD;
- `skill.generation` had no capability manifest (CI `test_h27_capability_manifests` was red) —
  manifest, refusal vocabulary and readiness row added;
- a created agent whose id is a common word (`what`, `status`, `research`) captured routing as a
  wake word — now refused with `409 routing_word`;
- rooms labelled replies as a retired agent's — now labelled `jarvis`;
- smaller: pending batch naming the deleted skill as `absorbed_into` now reported; mentions matched
  in any case; an agent batch's created skill is a journey node; bulk review keeps apply
  references; a pruned skill found gone stops asking for a reload; FLAGS.md documents that doors
  binding no sender are channel `unknown`.

Not changed, by decision: a skill batch deletes a pinned skill while the journey refuses one
(pre-existing H665 behaviour; the owner's batch is an explicit owner act).

## What is left to finish this PR (in order)

1. **Re-read the last 29 drifted ledger rows.** The batch moved evidence under 419 rows; 390 were
   re-read and stamped (commit "Hermes ledger: re-read 390 rows…"). The restamp run stopped on a
   usage limit before these were done, so they read `needs_review`:
   `H127, H091, H123, H124, H152, H423, H314, H073, H668, H078, H461, H338, H060, H072, H231, H488,
   H334, H326, H346, H594, H579, H475, H331, H665, H619, H147, H270, H234, H133`.
   Method per row (the same one every earlier batch used): `python scripts/hermes_restamp.py cite <ID>`
   lists which citations moved/edited; read `git diff origin/main...HEAD -- <its changed evidence>`;
   correct only what the diff made false (citations, counts, delivered `remaining` items, never the
   status); append the dated re-read note; build a JSON patch
   `[{"id","status","summary","remaining","evidence":[paths]}]` and run
   `python scripts/hermes_restamp.py stamp --patch <file>`. No hash-only restamps.
2. **Write the five new review entries** for H330, H389, H058, H202, H046, each `equivalent`.
   Contracts: `docs/handoff/hermes-2026-11-03/batch3-contracts.json`. Each summary starts
   "Built 2026-11-03 (batch 3, claude/hermes-batch3):", goes clause by clause against the
   contract with `path:line` citations into the current files, names how it is reached
   (route/CLI/chat/HUD/setting), the governance and the tests, and says honestly what was not
   proven (no live hub or real model). `remaining` is empty. Stamp them the same way.
3. `python scripts/hermes_status.py write && python scripts/hermes_status.py check` — expected
   headline **146/697** (141 + the five rows), `needs_review` 0.
4. `python scripts/status_sync.py --reuse-js-counts` (already run once: backend 31,432, 754 routes).
5. Add the BACKLOG note under HEQ-1 (section "Current sprint: Hermes capability equivalence"), after
   the "Batch 2 (2026-11-02)" paragraph: a "Batch 3 (2026-11-03)" paragraph in the same style
   (rows, what each delivers, the integration fixes, rows re-read, headline). H18.37 (native
   roster/journey) is already added; `mobile/PARITY.md` rows for H202/H046/H330/H058 are in.
6. Full suite as a **non-root** user (root ignores file modes and hides real failures), push,
   mark the PR ready, get CI green, squash-merge, then bump BACKLOG per `AGENTS.md`.

### Test baseline on this branch (full suite, non-root, Python 3.12)

All green except environment-only cases that fail in this sandbox and pass in CI:
`test_exec_cache` / `test_h667c_exec_cache_review` (docker/wasmtime unusable), `test_h350_skill_validator`,
`test_wasm_sandbox_h11_4`, `test_h517_named_provider_integration[tts]`, `test_jarvis_home`,
`test_dead_installer_stub`, `test_release_build`; `test_action_auth_matrix` has 3 cases that fail only
as root; `test_auth_audit_events::test_slow_lifecycle_sink_cannot_hold_new_credentials` is
timing-sensitive under full load (passes alone). `test_hermes_sprint_status` and
`test_release_gate::test_status_sync…` pass once steps 1–4 are done.
Frontend: `tsc` clean, vitest 276 files / 2,777+ tests green. Bandit (CI command) clean.

## Open owner decisions (not agent work)

- **Windows CI** — `test (windows-latest)` has hung ~6 h on every `main` push since #1321 and had
  ~624 failures on 2026-10-29. Proposal awaiting the owner: `timeout-minutes: 90` on that job and a
  WIN-2 BACKLOG task to restore the Windows suite.
- **Lean dev lane** — paused by the owner ("nu porni nimic"). Its four scheduled tasks
  ("Nerva lean dev run (slot 1–4 of 4)") still fire into the old Claude session, which skips
  them; disable or delete them in the scheduled-tasks UI if they should stop.
- **B2B pilot** — D1–D7 in `docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`.
- Other owner-only tasks: `docs/OWNER_TASKS.md`.

## After this PR: next Hermes rows

Pick from `scripts/hermes_status.py list --state partial` (or `--state missing`) (the BACKLOG driver in
`docs/prompts/BACKLOG_DRIVER.md` gives the order and gates). The working pattern that held up:
one worktree per row, implement against the pinned contract, then a fresh adversarial reviewer
per round (never the implementer), fix with a test that fails on the old code, repeat until the
reviewer finds nothing; then merge the rows, regenerate the generated files (tool surface
`python tests/test_tool_surface.py --update`, `schema.gen.ts` from the live server
`npm run typegen:openapi`, `scripts/gen_api_sweep.py`, the HUD bundle `npm run build`,
`python tests/test_capability_readiness_matrix.py --update`), run one more review of the merged
branch, restamp every drifted ledger row, and only then open the PR.
