# Parallel Development Playbook

> **Derived guidance.** The canonical source is [`AGENTS.md`](AGENTS.md). The machine-readable
> policy (`.github/ai-development-policy.json`) and its checker
> (`scripts/check_ai_workflow_policy.py`) were **removed by the owner de-gate decision** (#981,
> commit `824ff18`) and are archived in
> [`docs/restore/dev-gates-restore-2026-08-30.zip`](docs/restore/) (restore PRs #985/#986) — there
> is no checker to run, and nothing here is machine-enforced.

This playbook replaces the former vendor-specific OpenCode/Claude ownership table and local-only
lock protocol. Work is assigned by capability, risk, and current path intent—not by model brand.

## 1. Build a wave from path intent

For every proposed task, record:

```text
goal=<one outcome>
role=<planner|builder|verifier|reviewer|integrator>
risk=<R0|R1|R2|R3>
base_sha=<40-character SHA>
paths=<exact files or narrow path prefixes>
depends_on=<task/PR or none>
lease_expiry=<timestamp>
```

Automated verification receipts map CI risk conservatively (`low -> R0`, `medium -> R2`,
`high -> R3`). Use `R1` only with a specific bounded-internal justification.

Parallelize tasks only when their paths and contracts are independent. Shared generated files,
public contracts, migrations, branch policy, and status ledgers are serialization points even when
the implementation files differ.

## 2. Inspect before coordinating

Before editing:

1. Inspect the worktree and preserve all pre-existing changes.
2. Inspect open work when remote truth is relevant.
3. Compare exact paths, generated consumers, contracts, and merge order.
4. Continue when there is no material overlap.
5. When overlap exists, narrow the task, arrange an explicit handoff, or stop that mutation and
   escalate.

A draft PR does not own every file it touches. Draft status means “delivery is not ready”; it says
nothing about lease, CI, or governance state.

## 3. Planned GitHub-backed path leases

GitHub-backed path-prefix leases are the intended future coordination system, but they are not
implemented or enforced. Until a real service exists, report `lease=none`, inspect open work, and
coordinate overlaps explicitly. Do not claim `requested`, `active`, `contested`, `expired`, or
`released` as remotely verified state. Tracked as **DRA-26** in [`BACKLOG.md`](BACKLOG.md) and
scheduled post-1.0 ([`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md), Phase 7);
nothing in `agents/` implements it.

The planned lease record will contain:

- holder and purpose;
- exact path prefixes;
- base SHA;
- `requested`, `active`, `contested`, `expired`, or `released` state;
- expiry and last heartbeat.

Planned lease rules:

- keep path prefixes as narrow as possible;
- heartbeat only while work is active;
- expiry never proves another agent's work is safe to overwrite;
- contested leases stop the overlapping mutation, not unrelated work;
- release the lease immediately after handoff or abandonment.

`lock.py` remains an optional same-machine collision hint. Its local files do not synchronize,
cannot establish authority, and must not be treated as a repository-wide lock.

## 4. Capability roles and separation

| Role | Responsibility | Must not claim |
|---|---|---|
| Planner | scope, dependencies, risk, rollback | implementation verified |
| Builder | narrow implementation and targeted checks | independent approval |
| Verifier | reproduce and record exact commands/results | governance approval |
| Reviewer | consolidated spec/quality/security findings | merge authority by default |
| Integrator | confirm exact-head evidence and merge eligibility | fresh evidence after head changes |

Use the best available agent for the role and surface. For `R3`, builder, reviewer, and integrator
must be different actors/identities. For lower risk, roles may be combined when the policy permits.

## 5. Independent state dimensions

Report these four dimensions separately:

| Dimension | Typical states |
|---|---|
| Delivery | `planned`, `in_progress`, `draft`, `ready`, `blocked`, `merged`, `superseded` |
| CI | `not_run`, `running`, `passed`, `failed`, `cancelled`, `skipped`, `stale` |
| Governance | `unclassified`, `review_required`, `changes_requested`, `approved`, `owner_hold`, `stale` |
| Lease | `none`, `requested`, `active`, `contested`, `expired`, `released` |

Examples:

```text
delivery=draft ci=passed governance=review_required lease=none
delivery=ready ci=stale governance=stale lease=none
```

“Green”, “draft”, or “locked” alone is never a complete handoff.

## 6. Review loop budget

Normal review has at most two consolidated rounds:

1. one findings pass, grouped by severity and deduplicated;
2. one fix-verification pass against the new exact head.

If material findings remain, stop bouncing patches between agents. Escalate with the unresolved
finding, risk, options, recommended owner decision, and exact current head. A genuinely new scope or
new high-severity defect starts a separately identified review, not a hidden third round.

## 7. Evidence handoff

Handoffs and PRs use the receipt fields in `.github/pull_request_template.md`. Verification binds
to the exact head SHA and includes command, exit code, and result. A new commit moves prior CI and
governance evidence to `stale`; it must not be copied forward as if still current.

Evidence reuse is allowed only when:

- head SHA and policy version are identical;
- relevant inputs and environment class are unchanged;
- the receipt names its producer and generation time.

## 8. Safe Git sequencing

- Branch from a known base and keep unrelated work outside the task diff.
- Do not automatically rebase at session start. Rebase only an owned, clean feature branch when
  required for the task and safe for all present work.
- Prefer coherent rollback units. Local checkpoints are cheap; pushing every two-minute step is not
  a recovery strategy and needlessly restarts CI.
- Never push directly to `main` under the normal workflow.
- Integrate in dependency order after the exact-head receipt and required controls are current.

## 9. Recovery from collision

1. Stop only the overlapping mutation.
2. Capture `git status`, exact paths, current heads, overlapping open work, and uncommitted owners.
3. Preserve both contributions in separate branches/worktrees.
4. Decide the contract owner and merge order.
5. Re-run affected verification at the integrated head.
6. Record the explicit handoff/overlap disposition and report all four state dimensions
   (`lease=none` until enforcement exists).

Do not use age-of-file rules, local MD5 markers, or a model name as evidence that an edit is safe.
