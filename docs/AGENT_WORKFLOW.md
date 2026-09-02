# Nerva AI Development Workflow

> **Derived human-readable guide.** The canonical source is [`AGENTS.md`](../AGENTS.md); when this
> guide disagrees with it, `AGENTS.md` wins. There is no longer a machine-readable policy or a
> checker behind this document: `.github/ai-development-policy.json` and
> `scripts/check_ai_workflow_policy.py` were removed by the owner de-gate decision (#981, commit
> `824ff18`) and archived in [`docs/restore/`](restore/).

This workflow keeps AI-assisted development fast without converting speed into rework. It applies
to feature work, fixes, refactors, security changes, CI/governance work, and multi-agent sessions.

## Risk first

> **Advisory since #981.** The R0–R3 tiers below are a convention agents follow, not a gate GitHub
> enforces — see [`AGENTS.md`](../AGENTS.md) → "Development posture". Nothing fails a PR if a tier
> is mis-assigned; the value is in choosing the right amount of test and review for the change.
> Two facts to keep in mind (CTO, 2026-09-02): `pr-auto-merge.yml` merges any non-draft PR GitHub
> reports CLEAN, hourly, with no review; and the PR checks re-gated on 2026-09-02 (`test` incl. the
> test-count drift step, `hud-v2-build`, security-scans, lockfile-drift) become blocking only once the
> owner lists them as required in branch protection (owner item under A4 in
> [`docs/OWNER_TASKS.md`](OWNER_TASKS.md)).

Classify the smallest coherent change before implementation:

| Tier | Typical scope | Minimum posture |
|---|---|---|
| `R0` | prose, comments, non-executable diagrams | scope/content check + policy lint |
| `R1` | tests, developer tooling, internal no-contract refactor | design summary + targeted tests + diff review |
| `R2` | runtime, API/contract, dependency, generated truth, user-facing behavior | design receipt + regression + independent review *recommended* (not required since #981) + relevant full CI + rollback |
| `R3` | security/authority, credentials, destructive/external writes, release governance, migrations | failure model + owner/policy gate + independent review *recommended*; runtime/security changes get a **recorded post-merge attestation in `BACKLOG.md`** (the SEC-B4 / SEC-B6 / #911 model from #1009) + rollback proof |

When uncertain, choose the higher tier until evidence narrows it. Split mixed-risk work when the
pieces can ship independently.

Automated verification receipts map CI risk conservatively: `low -> R0`, `medium -> R2`, and
`high -> R3`. `R1` remains available for a justified bounded-internal human classification.

## 1. Observe before mutating

Capture:

- requested outcome and authorization boundary;
- `git status`, current branch, base SHA, and pre-existing changes;
- exact paths and contracts likely to change;
- overlapping open work when current remote state matters;
- owner, hardware, credential, or live-service gates.

Do not automatically fetch/rebase for every task. Fetch when remote truth is necessary. Rebase only
an owned feature branch when the worktree is clean, the base is known, no user changes are present,
and the task actually needs the rebase. A dirty worktree or read-only task is a stop condition for
automatic history mutation.

## 2. Create a design receipt

For `R1+`, record enough for a fresh contributor to execute or reject the approach:

```text
Goal:
Non-goals:
Risk tier and reason:
Likely changed paths/contracts:
Test strategy:
Rollback:
Dependencies and path lease:
```

For `R3`, add a threat/failure model, authority boundary, separate builder/reviewer/integrator, and
the owner or policy gate. Design is a decision aid, not permission to expand scope.

## 3. Plan a coherent rollback unit

Prefer steps that produce one independently reviewable outcome. Each step names exact paths,
behavior, checks, and expected result. Local checkpoints may be fine-grained; do not push after
arbitrary two-to-five-minute units and restart CI without useful new evidence.

Use TDD when behavior can be pinned by a regression:

1. demonstrate the failure;
2. implement the narrow fix;
3. demonstrate the targeted pass;
4. refactor only inside the authorized scope while keeping evidence green.

## 4. Coordinate by intent, not vendor

Route roles by capability: planner, builder, verifier, reviewer, integrator. A draft PR advertises
unfinished delivery; it does not lock its paths. GitHub-backed path leases are planned but not
implemented, so inspect open work and arrange an explicit handoff when overlap needs serialization.
Local `lock.py` state is only an advisory same-machine hint.

For parallel waves, compare both direct paths and indirect collision surfaces:

- generated documents and registries;
- public schemas/routes/contracts;
- migrations and dependencies;
- branch/governance configuration;
- status and roadmap ledgers.

For `R3`, separating builder, reviewer and integrator is recommended, not enforced (de-gated in
#981): what is recorded instead is the post-merge attestation row in `BACKLOG.md` — a reviewer
distinct from the builder, bound to the merged SHA, ending in PASS/HOLD (the SEC-B4 / SEC-B6 / #911
model from #1009).

## 5. Verify the exact head

At minimum, run targeted checks for the changed surface. Broader suites are selected by risk and
merge policy, not by habit. An evidence receipt contains:

```text
policy_id=nerva-ai-development-v1
policy_schema_version=1
head_sha=<exact 40-character commit>
risk_tier=<R0|R1|R2|R3>
changed_paths=<path manifest>
commands=<ordered command manifest>
results=<command, exit_code, summary records>
producer=<actor/automation>
generated_at=<timestamp>
```

A test claim without a receipt is advisory. Evidence can be reused only for the identical head SHA
and policy version with unchanged relevant inputs. Any new commit makes prior check and approval
state stale.

## 6. Review with a bounded loop

Normal review is capped at two consolidated rounds:

1. spec, correctness, security/privacy, test, and scope findings in one deduplicated pass;
2. verification of fixes at the new exact head.

After round two, escalate unresolved material findings with severity, evidence, options, owner, and
the recommended decision. Do not create an unbounded reviewer/fixer loop. A new high-severity issue
or genuinely new scope is labeled as a new review event.

## 7. Keep state dimensions separate

Report all relevant state machines rather than compressing them into “green”:

- delivery: `planned` → `in_progress` → `draft` → `ready` → `merged`;
- CI: `not_run` / `running` / `passed` / `failed` / `cancelled` / `skipped` / `stale`;
- governance: `unclassified` / `review_required` / `changes_requested` / `approved` /
  `owner_hold` / `stale`;
- lease: `none` today; the other canonical states are reserved for the planned enforced service.

The canonical JSON defines all allowed transitions, including blocked and superseded delivery.

## 8. Integrate and finish

Before ready/merge:

- re-read the scoped diff and confirm no unrelated changes;
- confirm the PR template names exact head, risk, states, and receipts;
- confirm required controls for the tier and any parity/generated consumers;
- ensure approval and CI refer to the current head;
- record the overlap/handoff disposition without claiming a remote lease.

Finish with delivery, CI, governance, and lease states plus one next safe action. Examples:

```text
delivery=ready ci=passed governance=approved lease=none
head=<SHA> next=integrator may merge
```

```text
delivery=blocked ci=failed governance=owner_hold lease=none
head=<SHA> next=owner chooses rollback or credentialed live validation
```

## Queue posture near 1.0

Prefer runtime bugs, security boundaries, CI/governance confidence, dependency safety, and truth
repair before new scaffolding. Hardware/live-service work stays held until its real environment can
produce evidence. Historical plans and unchecked boxes do not override the current machine ledger
or an explicit owner decision.

## Privacy and external tooling

Nerva remains local-first. Do not vendor an external agent-methodology runtime or transmit private
context because a development plugin suggests it. External tools must stay inside the task's
authorization, privacy, and risk controls.
