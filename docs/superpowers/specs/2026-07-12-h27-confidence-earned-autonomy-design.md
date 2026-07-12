# H27.7 confidence and earned autonomy — design

## Goal

Feed real per-action execution outcomes into the existing capability registry and allow a narrowly
bounded, default-off earned-autonomy step without weakening hard safety floors.

## Non-goals

- Do not change action risk classification or claim that a risky action became intrinsically safe.
- Do not lower `IRREVERSIBLE_OR_MONEY`, money, explicit `ASK/OFF`, tainted-input, kill-switch,
  capability-token, contract, or budget gates.
- Do not count approvals, rejections, retries, dry runs, or executor-less `noop` completions as
  successful capability outcomes.
- Do not finish the 70 remaining H27.5 reality cases in this PR.

## Outcome ledger

Extend the existing `TaskQueue` SQLite database with an additive `capability_outcomes` table keyed by
capability id. The worker resolves terminal task kinds through `manifest_for_action`, records one
success for a real `DONE`, one failure only after the retry budget reaches terminal `FAILED`, and no
row for unknown actions or `noop`. The table stores success/failure counts and the last update time;
it contains no task payload or personal data.

Confidence is the 95% Wilson lower bound for the observed success rate, rounded and clamped to
`0..1`. This deliberately starts at zero, penalizes small samples, drops immediately after failures,
and survives process restarts. Registry action records expose the calculated confidence and outcome
counts. Other capability kinds stay at zero until they acquire an equivalent real outcome source.

## Earned-autonomy rule

`AutonomyPolicy` gains an `earned_autonomy_enabled` switch, default false, live-synced from the
existing settings path `autonomy.earned_autonomy_enabled`. The worker binds a private outcome
provider backed by the queue; caller payloads cannot inject or spoof confidence. In `auto` mode only,
at `samples >= 20` and `confidence >= 0.80`, policy
may lower the outcome by exactly one rung (`ASK → NOTIFY` or `NOTIFY → ACT`) while retaining the
original risk tier in the decision/task/audit record.

Hard floors are evaluated before/after this step:

- tier 3 (`IRREVERSIBLE_OR_MONEY`) is never lowered, including money within configured caps;
- explicit global/per-agent `ask` and `off` modes are never lowered;
- tainted input is still forced to `ASK` by the worker after policy evaluation;
- all kernel, contract, token, budget and kill-switch gates remain authoritative.

The decision reason carries the sample/confidence provenance when a rung is earned.

## Files

- `agents/core/autonomy/queue.py`
- `agents/core/autonomy/worker.py`
- `agents/core/autonomy/policy.py`
- `agents/core/observability/capability_registry.py`
- `agents/core/orchestrator.py`, `agents/core/autonomy_coordinator.py`
- focused queue/worker/policy/registry tests and generated status/backlog docs

## Risks and mitigations

- **False success:** terminal `FAILED` records once; intermediate retries do not. `noop` is ignored.
- **Confidence inflation:** Wilson lower bound + minimum sample threshold; unknown capabilities ignored.
- **Approval bypass:** one-rung maximum, explicit-mode/taint/tier-3 floors, and existing kernel remains
  outside this policy convenience layer.
- **Concurrency:** outcome updates use the queue's existing lock and SQLite upsert transaction.
- **Migration:** additive `CREATE TABLE IF NOT EXISTS`; rollback is a code revert, leaving an inert
  table that older versions ignore.

## Tests

- exact Wilson/stat persistence and concurrent-safe upsert behavior;
- worker success/failure/retry/noop/unknown accounting;
- registry confidence/stat projection;
- default-off and threshold behavior;
- one-rung maximum plus explicit `ASK/OFF`, taint and tier-3 hard-floor regressions;
- focused autonomy/kernel/H27 suites, full CI on Ubuntu and Windows, SAST and status-sync.

## Rollback

Revert the PR or set `autonomy.earned_autonomy_enabled=false` (the default). The additive SQLite table
may remain safely unused; no destructive migration is required.
