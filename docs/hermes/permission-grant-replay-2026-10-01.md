# Task-bound permission grants

- Goal: close duplicate effects when a `permission.grant` task is retried.
- Base: `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`.
- Implementation: `b7a15e89993bd5560ee03f4e7a40a99621132fbf`.
- Review correction: `d2e065c4ed6171c0f439fd61a0748189e2d531ed`.
- Generated: 2026-10-02; local only, no publication or deployment.
- Changed source: `agents/core/permission_ledger.py` and
  `tests/test_permission_ledger.py`.

## Contract

A positive approved task ID now owns one durable grant receipt. The normalized
authority fields and governed payload must match on replay. A SQLite write
transaction serializes receipt lookup, legacy adoption, grant insertion, audit
and receipt persistence. A pre-commit failure rolls the effect back; a commit
that succeeds and then reports an error is recovered by returning the original
grant on retry. Revoked, consumed or expired authority is never reactivated.
The result includes the persisted `grant_status`.

Migration adds a receipt table without deleting or rewriting existing grants.
Exactly one matching legacy grant can be adopted. Multiple legacy grants for
one task refuse that task; the ledger still opens and unrelated tasks work.
Legacy metadata that was never persisted cannot be reconstructed retroactively.

OS-input restore tokens are written before the SQL grant commits. A token-store
failure rolls back the grant. A process interruption after a successful commit
therefore leaves the original token available; replay never mints another.
A failed or uncertain SQL commit can leave an orphan token, which is unusable
because restoration requires an existing active OS-input grant. Ambiguous commit
does not delete the token: the SQL commit may already have succeeded.

## Verification and review

The initial regressions failed before the implementation. The final focused run
passed **106 tests** across `test_permission_ledger.py`,
`test_action_auth_matrix.py` and `test_autonomy_worker.py`; scoped Ruff and
whitespace checks passed. Tests use real SQLite with injected audit/commit faults,
restart, concurrent ledger instances, payload mismatches, inactive grants,
legacy duplicates and OS-input token recovery.

Independent review found the first implementation's token-after-commit process
window. Two red-first regressions drove the correction above. Re-review found
no remaining concrete blocker in the scoped diff. Full repository verification
belongs to the later integration milestone, not this focused result.

## Limits and next action

This does not repair historic duplicate grants or change their authority silently.
All workers must use the corrected code; an old process can still run old logic.
SecretStore's existing cross-process and power-loss durability limitations remain;
the tests prove process-retry semantics, not atomic transactions across two stores.
Safe orphan-token reclamation requires separate reconciliation work.

Next action: integrate the local batch and run full suites; continue the remaining
handover defects. Rollback the two local implementation commits together, preserving
the new receipt table and owner data. Reverting the code restores the duplicate-
effect vulnerability; it is not a schema/data cleanup operation.
