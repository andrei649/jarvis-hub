# Local sprint: H277 round 2

Generated: 2026-09-27. Base/head before this batch:
`bd2bb70ead1b493043a335e77713fc42c47d4013`, plus existing owner-approved local
policy and parity-inspection diffs. No commits or publication in this batch.

## Goal and boundaries

Close the round-2 backend, HUD and role-locality defects in
`docs/handoff/h277/fix_round2_brief.md`. Preserve advisory-only behavior, explicit
remote opt-in and the original no-judge shape. This batch does not include the
kernel extension, full Hermes parity or completion of H277's broader requirements.

## Ownership and dependencies

| Role | Model / effort | Owned paths |
|---|---|---|
| Coordinator | Current app selection | `AGENTS.md`, this record; review and integration |
| Backend implementer | `gpt-6-sol` / `high` | `agents/core/autonomy/action_approvals.py`, `agents/core/autonomy/approval_judge.py`, `tests/test_h277_approval_judge.py`, H277 flags documentation |
| HUD/roles implementer | `gpt-6-sol` / `high` | `agents/web/static/tools.js`, `tests/frontend/tools.test.js`, `agents/core/llm/model_roles.py`, `tests/test_h277_model_roles.py` |

No subdelegation. Backend-to-HUD contract: each public approval exposes
`judge_pending: true` only while a judgment is queued or running. It is runtime
state, never persisted, and is cleared when finished, skipped or decided. HUD
uses the per-item field and a per-card wall-clock cap of `17 * timeout + 5`
seconds. Independent source ownership permits parallel implementation after
agreeing this contract.

## Verification and rollback

Implementers first demonstrate failing regressions, then run their focused
Python/legacy Vitest suites. Coordinator reviews the diffs and runs combined
relevant checks after integration. Existing full-suite/mutation obligations stay
open until actually executed; no completed H277 ledger claim from this batch alone.

Rollback is the reverse of this batch's exact diff, preserving earlier policy,
inspection and other user changes. No service, personal data or remote state is
part of the rollback.

## Results

Both Sol High agents completed their assigned edits and stopped. No nested agents
were spawned. The coordinator reviewed both diffs, identified two additional
regressions (small-value budget inflation and legacy double-prime sanitization),
and the backend implementer added tests and fixes before integration.

- N1: dispatch checks current policy and pending memory/disk state after obtaining
  a slot, inside the timeout coroutine; revoked work is counted without sending.
- N2: runtime-only per-card pending state is separate from queue capacity; the HUD
  uses a refresh-resistant wall-clock deadline and displays late opinions.
- N3/N4/N6: valid bounded JSON preserves keys and small values, scans normalized
  bytes/collections, and rejects remotely unsafe depth or unrepresentable keys.
- N5/N7: rationale normalization retains prior defenses; unavailable judge imports
  do not fail requests, and an unconfigured judge preserves the original item shape.
- F4 and F6/F7: direct deep-taint refusal and LAN vision locality are pinned.

### Executed verification

- Implementer RED: backend defects reproduced before fixes; frontend four new
  failures and LAN-label failure reproduced. Late-opinion test was also run
  against original source to isolate the premature six-second polling cutoff.
- Coordinator integration: **467 passed**, using normal project pytest options:

  ```text
  .venv/bin/python -m pytest tests/test_h277_approval_judge.py tests/test_h277_model_roles.py tests/test_action_approvals_persist.py tests/test_h10_18_action_approvals.py tests/test_h659_idempotency.py tests/test_h378_selection_guards.py tests/test_llm_provider_profiles.py tests/test_vlm_h13_1.py tests/test_model_config.py tests/test_skill_approval_revoke.py tests/test_h318g_skill_review.py tests/test_h318h_skill_review.py
  ```

- Legacy HUD suite: `node node_modules/vitest/vitest.mjs run tests/frontend` —
  **227 passed / 27 files**. This is not the separate `frontend/` application suite.
- Ruff passed on changed Python implementation/tests and the existing policy diff.
- Bandit **1.9.4**, the CI-pinned version, passed on the three changed H277 Python
  modules against `.bandit-baseline.json`, from a disposable tool environment.
- `git diff --check` passed. Scoped Graft source index rebuilt after edits.
- Non-failing warnings: Starlette/httpx deprecation and Vite config-loader notice.

Account-wide weekly usage read 3% before the batch and 4% after verification.
These are rounded shared-account readings, not attributable per-agent costs or a
claim that this batch consumed exactly one percentage point.

### Still open

The handoff's 49 prepared mutation cases, full backend and separate frontend
suites, H277 evidence/ledger updates, and kernel/Decision Inbox extension have not
been completed in this batch. H277 remains partial; no parity metric is promoted.
Revocation cannot retract an already dispatched call. JSON persistence remains a
single-owner store, not a cross-process transaction protocol.

Next action: execute the mutation verification on the settled diff before H277
records or kernel expansion. Keep source mutations isolated from active editors.
