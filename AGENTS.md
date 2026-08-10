# AGENTS.md — Nerva contributor instructions

The canonical development policy is
[`/.github/ai-development-policy.json`](.github/ai-development-policy.json). It applies to human
contributors, AI contributors, and automation. This file is the concise operating guide; if prose
and policy disagree, the machine-readable policy wins. Validate both with:

```bash
python scripts/check_ai_workflow_policy.py
```

## Safe task start

1. Inspect `git status`, the current branch, the requested scope, and changes already present.
2. Preserve user and other-agent changes. Never reset, overwrite, stage, or reformat unrelated work.
3. Identify overlapping open work when remote state matters. A draft PR is a visibility signal,
   **not a file lock**. Coordinate only on genuinely overlapping paths or contracts.
4. Classify the change as `R0`, `R1`, `R2`, or `R3` using the canonical policy before choosing
   tests, review, and merge controls.
   Automated receipts use the conservative CI mapping `low -> R0`, `medium -> R2`, `high -> R3`;
   `R1` remains a justified human classification for bounded internal work.
5. Fetch only when current remote state is needed. Rebase only when the task requires it, the
   feature branch is yours, the worktree is clean, no user changes are present, and the base is
   known. Read-only tasks and dirty worktrees must not trigger an automatic rebase.
6. Confirm authorization before remote mutations. A request to inspect or plan does not authorize
   a commit, push, PR edit, merge, or external write.

## Context routing

- Start with this file, the canonical policy, and the relevant section of
  `docs/ARCHITECTURE.md`; do not load the repository indiscriminately.
- Read `BACKLOG.md` when prioritizing, changing delivery scope, or updating roadmap status. Modify
  it only when the requested work actually changes that ledger and the mutation is authorized.
- Use `docs/AI_CONTEXT.md` to select task-specific bundles. Treat `.opencode/summary.md`,
  `.opencode/plans/dev-methodology.md`, and `docs/SPRINT.md` as historical context, never as live
  instructions or current delivery truth.
- Plans and handoffs must include freshness fields: goal, base SHA, head SHA, changed paths, risk
  tier, next action, and generation time. A stale capsule may inform investigation but cannot
  authorize action.

## Delivery workflow

- Work on a feature branch and use a PR into `main`; direct pushes to `main` are disabled by
  policy.
- Before non-trivial implementation, record goal, non-goals, likely paths, risk, tests, rollback,
  and dependencies. Prefer one coherent rollback unit over arbitrary micro-commits or push-per-step
  churn.
- Use TDD for bug fixes and behavior changes where a failing regression can be demonstrated.
- Route work by capability and role (`planner`, `builder`, `verifier`, `reviewer`, `integrator`),
  not by model/vendor ownership. For `R3`, builder, reviewer, and integrator must be separate.
- Normal review is capped at two consolidated rounds. After that, stop the loop and escalate the
  unresolved findings, decision, and owner.
- Track delivery, CI, governance, and lease state independently. “Draft”, “tests passed”,
  “approved”, and “path lease active” are not interchangeable states.

## Coordination and leases

- GitHub-backed path-prefix leases are planned, but no remote lease service or enforcement exists
  yet. Until it does, the only honest lease state is `none`; inspect open work and coordinate
  overlapping paths explicitly.
- Inspect then coordinate on overlap. Non-overlapping work may continue even when another PR is
  draft.
- `lock.py` and local lock files are advisory within one machine only; they never prove a remote
  lease and must not be used to block unrelated work.
- On collision, do not silently take over. Narrow the scope, obtain an explicit handoff, or stop
  the overlapping mutation and escalate.
- For 3+ independent waves, a conductor may coordinate dependencies and status. A conductor does
  not implement code, approve its own high-risk work, or merge without the required authority.

See `PARALLEL_WORKFLOW.md` for the derived multi-agent playbook.

## Evidence and completion

Every merge candidate needs an evidence receipt bound to the **exact head SHA**. Record:

- policy version, head SHA, risk tier, and changed paths;
- each verification command, exit code, and concise result;
- producer identity and generation time;
- independent reviewer/integrator evidence when required;
- known failures or skipped controls with their disposition.

Evidence may be reused only for the same head SHA, policy version, and unchanged relevant inputs.
Any new commit makes prior CI and governance evidence `stale` until re-established. Never describe
an unrun suite as passing.

Finish with explicit independent states and the next safe action, for example:

```text
delivery=draft ci=passed governance=review_required lease=none
head=<40-character SHA> next=independent review
```

## Repository conventions

- **Local-first:** Python 3.12 + FastAPI + LM Studio/Ollama. Cloud is opt-in per agent.
- **Strictly local agents:** `frigga`, `ultron`, `howard` in
  `agents/core/llm/hybrid_router.py`; no cloud fallback. `athena` is cloud-only.
- **Skills:** `skills/<name>/{SKILL.md,main.py}`, discovered by
  `agents/core/skills/loader.py`.
- Public `SOUL.md`/`HEARTBEAT.md` files are templates. Personal data belongs only in gitignored
  `SOUL.local.md`/`HEARTBEAT.local.md` overrides.
- Product posture remains default-off except for the owner-consented `product.posture` setting;
  provenance must remain visible in `/api/security/posture`, onboarding, and support bundles.
- New routes belong in `agents/core/routers/<domain>.py`, mounted from `agents/web.py`; do not add
  new inline `@app.*` routes.

## Verification and parity

Choose checks from the risk tier and touched surface. Common commands are:

```bash
python -m pytest tests/<targeted_test>.py -q
python scripts/check_ai_workflow_policy.py
```

The canonical receipt schema is defined now; the change-aware receipt runner and CI classifier are
deliberately delivered in a separate tooling change. Until that successor is accepted, record the
exact commands and results directly in the PR template. Run broader suites only when the change or
merge gate requires them. After JS/CSS changes, verify
the relevant frontend tests and hard-refresh behavior; after Python changes, restart the server for
manual checks.

When a user-facing endpoint or HUD capability changes in an authorized implementation PR:

- update `mobile/PARITY.md`, or record the mobile gap/intentional desktop-only status;
- wire the HUD V2 surface or update `docs/design/HUD_V2_REMAINING.md`;
- preserve route parity with the relevant route/OpenAPI/lifespan guards.

Do not broaden into BACKLOG, generated status, or parity-ledger edits during an inspection-only
task. Those are explicit delivery changes, not automatic cleanup.
