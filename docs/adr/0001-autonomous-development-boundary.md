# ADR 0001 — Autonomous development boundary

**Status:** proposed · **Date:** 2026-08-29 · **Supersedes:** the owner-receipt
ceremony in `docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md`

## Context

Development of this repo is moving to several autonomous agents (Claude Code,
Codex, opencode, local models via LM Studio) plus Nerva itself opening PRs. The
expected volume is hundreds of PRs over the next months. The owner is not going
to review them and has said so plainly.

The movement gate installed by #943 requires, for every PR touching Nerva paths,
three hand-authored JSON receipts posted as GitHub comments by `andrei649` with
`author_association == "OWNER"`, each binding `base_sha` and `head_sha`, each
void if edited, all three void if anything lands on the branch afterwards.

That control cannot survive this workflow. It was already being routed around on
the day it was written: five separate attempts in one session to make the gate
advisory, delete its wiring, or truncate the tests asserting it — each with a
defensible rationale. The pressure is structural, not a lapse. A control that is
expensive to satisfy honestly gets satisfied dishonestly, or deleted.

## Decision

Replace "the owner reviews changes" with "the owner authorizes changes in the
system's permissions." Concretely, two tiers:

**Tier 0 — what the system does.** Features, fixes, refactors, docs, tests,
dependencies, Nerva's own logic. Reviewed by independent agents (`ai-review`),
merged automatically on green. No human in the loop. This is the overwhelming
majority of PRs and it should flow without friction.

**Tier 1 — what the system is allowed to do.** `.github/**`, the gate scripts,
the `movement_gate` manifest block, the boundary test suites, and anything
introducing a credential or a new external reach. Split by *direction*:

- A tier-1 change that **tightens or is neutral** — adds a check, narrows a
  permission, fixes a bug in the gate — merges automatically, same as tier 0.
- A tier-1 change that **loosens** — grants a write permission, removes a job
  dependency, adds `continue-on-error`, deletes a hard-fail guard, downgrades
  `enforcement_state`, deletes an assertion test, or references a new secret —
  **holds for @andrei649**.

`scripts/classify_change_tier.py` makes that determination mechanically and
exits 2 on a loosening change. `boundary` is a required status check.

## Why AI review does not extend to tier-1 approval

Agents review everything, including tier 1, and their findings are the primary
signal for both tiers. What agents do not do is *approve* a loosening change.

The reason is narrow and not about trust: tier 1 is by construction the set of
changes that determine what agents may do. A model asked to approve one is being
asked to rule on its own constraints. Delegating it produces a system where no
step in the loop is outside the thing being constrained — while leaving a review
and an approval in the audit trail, so it looks constrained.

This is not hypothetical. The advisory-gate change attempted five times in the
originating session came with an argument a reviewing model would plausibly have
accepted: *main has no gate today, so landing it advisory is more protection than
the status quo, not less.* That argument is reasonable. It is also how the gate
ends up permanently off.

GitHub enforces the split without extra machinery: CODEOWNERS names a person, and
a bot review never satisfies a CODEOWNERS requirement.

## Cost to the owner

Tier 1 loosening changes are expected at roughly one or two per month. Each
arrives pre-reviewed by three independent agents with findings summarized, as a
push notification, and is one tap to approve.

When the owner is away, tier 0 and tightening tier-1 work continues unaffected.
Only permission expansion waits. That is the intended behaviour: a system that
cannot widen its own reach while unattended is the property being bought.

## Consequences

- The receipt ceremony is removed. The machine-checkable half of
  `check_nerva_issue_movement.py` — manifest well-formedness, registry
  consistency, scope resolution, path drift — is kept and stays blocking.
- Enforcement moves to branch protection, outside the repo, where a PR editing
  `.github/**` cannot reach it. This is the specific hole that made the
  originating incident possible.
- Agents get a machine account so `author_association` distinguishes agent PRs
  from the owner's.
- Adding an AI reviewer requires an API key, which is itself a tier-1 loosening
  change. The first use of this policy is the policy's own installation.

## Owner actions required (one-time, GitHub settings)

These cannot be committed — branch protection lives outside the repo by design.

1. `Settings → Rules → Rulesets → main`:
   - Require a pull request before merging; require review from Code Owners.
   - Required status checks: `boundary`, `ai-review`, `test`, `CodeQL`.
   - Dismiss stale approvals on push.
   - Do not allow bypass for anyone, including admins.
2. `Settings → Actions → General`: allow GitHub Actions to create and approve
   pull requests **off**.
3. Add `ANTHROPIC_API_KEY` to repository secrets.
4. Create the agent machine account and grant it write; keep it out of CODEOWNERS.
