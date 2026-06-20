# Jarvis Hub Agent Workflow

This document adapts the useful parts of the external Superpowers methodology to Jarvis Hub.
It is an operating protocol for coding agents, not a runtime dependency and not vendored code.

Source reference: `obra/superpowers` describes itself as a software-development methodology for coding agents, built from composable skills and startup instructions. Its core workflow emphasizes brainstorming, worktrees, plans, TDD, review, and finishing branches cleanly.

## Scope

Use this workflow for any non-trivial Jarvis Hub work:

- security hardening,
- feature work,
- refactors,
- bug fixes with uncertain root cause,
- multi-agent sessions,
- release-gate or branch-protection changes.

For tiny docs fixes or Dependabot bumps, apply the lightweight path only: inspect, verify checks, report risk, merge only when safe.

## Non-negotiables

1. **No big code before design.** For feature/security/refactor work, write a short design note first: goal, constraints, files likely touched, risk, tests, and rollback.
2. **Work in branches.** Do not push directly to `main`; use a feature branch and draft PR unless the user explicitly asks for a direct emergency hotfix.
3. **Evidence over claims.** Every PR must include the exact verification command and result. If a failure is unrelated, prove or explain why.
4. **TDD where practical.** For bug fixes and core behavior changes, add or update a failing regression test before the fix. Then make it pass.
5. **Keep work small.** Prefer small PRs that can merge independently. Do not bundle cleanup, refactor, dependency bumps, and feature work unless necessary.
6. **Respect active draft PRs.** A draft PR owns its touched files until it merges, closes, or the user explicitly reassigns the work.
7. **Finish the branch.** A task is not done until status is reported: merged, queued for auto-merge, blocked by checks, draft/hold, or closed as superseded.

## Standard workflow

### 1. Understand and triage

Before editing:

- read `BACKLOG.md`, `STATUS.md`, and relevant docs,
- inspect open PRs touching the same area,
- check whether the work is owner-gated, hardware-gated, or blocked by live credentials,
- identify the smallest safe change.

### 2. Design note

For non-trivial work, include a short design note in the PR body or a `docs/plan-*.md` file:

```text
Goal:
Non-goals:
Files likely touched:
Risk:
Tests:
Rollback:
Merge order / dependencies:
```

Large features should not proceed beyond scaffolding until the design is reviewed.

### 3. Implementation plan

Break the change into steps a fresh agent could execute:

- exact file paths,
- exact behavioral change,
- tests to add or update,
- verification command,
- expected result.

### 4. Implementation

Use the narrowest change that satisfies the design. Avoid opportunistic cleanup outside touched files unless the user asked for an audit/cleanup pass.

### 5. Verification

At minimum, run the most relevant targeted tests. For merge candidates, prefer:

```bash
python -m pytest tests/<targeted_test>.py -q
python -m pytest tests/ -q
npm test
npm run test:coverage
```

Use the actual commands for the touched surface. Do not claim a suite passed unless it was run and returned success.

### 6. Review

Before marking ready:

- re-read the diff,
- check for branch conflicts,
- check security/privacy implications,
- check UI/mobile/HUD parity ledgers when user-facing APIs changed,
- update `BACKLOG.md`, `STATUS.md`, or owner tasks only when the change actually moves those trackers.

### 7. Finish

End every work session with one of these statuses:

- `merged`,
- `auto-merge enabled`,
- `ready but waiting checks`,
- `draft / hold`,
- `blocked by owner action`,
- `closed as superseded`.

Also state the next safe action.

## PR queue policy

When many PRs are open, prioritize in this order:

1. real production/runtime bugfixes,
2. security hardening,
3. CI or branch-rule fixes that improve merge confidence,
4. small dependency updates with green checks,
5. docs truth-sync,
6. large dependency surfaces that need manual validation,
7. draft feature scaffolds.

Hold mobile, WorldView/live integration, GPU, mic, and owner-settings PRs until the relevant real hardware or live service has been validated.

## ChatGPT / Jarvis operator mode

When ChatGPT is used as the repo conductor, it should:

- inspect open PRs before suggesting new work,
- avoid opening overlapping work while draft PRs exist,
- prefer queue reduction over feature expansion near v1.0,
- explicitly separate what it can change in GitHub from what Andrei must do in ChatGPT settings or on the RTX box.

## Privacy and external tooling

Do not vendor external agent-methodology repositories into Jarvis runtime unless explicitly approved.
If using Superpowers in a local coding harness, set telemetry opt-outs in the shell or `.env` used by that harness:

```bash
SUPERPOWERS_DISABLE_TELEMETRY=true
DISABLE_TELEMETRY=true
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=true
```

These are development-environment settings. Jarvis runtime must remain local-first and privacy-first.
