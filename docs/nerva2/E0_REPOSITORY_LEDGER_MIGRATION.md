# Nerva 2.0 E0 repository-ledger migration

> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Applied state:** exact repository reconciliation is present; E0 remains `VERIFYING` and `close_e0=false`.

## Purpose

`BACKLOG.md` and `STATUS.md` are large historical ledgers. Reconstructing either file from partial
API output risks deleting delivery history, changing unrelated generated content or creating a false
E0 closure claim. `scripts/reconcile_nerva_repository_ledgers.py` supplies one bounded and reusable
way to apply and continuously verify the reviewed Nerva blocks from a complete worktree.

The migrator is not another program manifest and does not replace
`docs/nerva2/E0_COMPLETION.json`. It performs a byte-preserving insertion at one unique stable anchor
per ledger, then becomes an idempotent verifier of the exact marker-bounded content.

## Safety properties

- reads and writes UTF-8 bytes without newline normalization;
- preserves LF or CRLF at the insertion site;
- validates both ledgers before writing either one;
- refuses missing, duplicate or ambiguous anchors;
- refuses partial, duplicate or stale marker-bounded blocks;
- writes atomically and preserves existing file modes;
- proves that removing the inserted block reproduces the original input exactly;
- keeps E0 `VERIFYING`, all first-wave issues blocked and Ultron as the sole privileged-action
  authority.

## Applied evidence

The E0.3b2b delivery workflow used locked dependencies to:

1. run the existing project-status generator with tracked frontend/mobile counts;
2. apply both reviewed ledger blocks from the complete checkout;
3. run the migrator in `--check` mode;
4. run `scripts/status_sync.py --check`, both Nerva checkers and the focused migrator tests;
5. enforce an exact generated-file allowlist and `git diff --check`;
6. commit the generated reconciliation and remove the one-shot workflow itself.

The resulting change set contains one insertion in each ledger plus normal generated-status updates to
`project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md` and the volatile counters in
`STATUS.md`. The tracked backend count moved from 5,731 to 5,743 because the new tests are now part of
the collected suite.

The complete #778 body is reconciled through a separate authoritative snapshot and repository evidence
in `E0_778_BODY_RECONCILIATION.md`; its B0–B10, M0–M8, metrics and anti-drift plan remain intact.

## Verification commands

```bash
python scripts/reconcile_nerva_repository_ledgers.py --check
python scripts/status_sync.py --check
python scripts/check_nerva_roadmap.py
python scripts/check_nerva_e0_completion.py
python -m pytest tests/test_reconcile_nerva_repository_ledgers.py -q
```

The dedicated Nerva workflow runs the repository-only ledger and Nerva checks; full CI independently
runs the generated-status release gate and the Linux/Windows test suites.

## Explicit non-claims

The applied ledger blocks and issue reconciliation do **not** close E0, unblock #780–#784 or implement
any Nerva runtime capability. E0 closure remains a separate independent integrator decision after the
final exact-head generated-status checks and all required CI are accepted. Broader B2 whole-program
manifest work and B3–B10 remain open.

## Next slice

**E0.3b2b-independent-closure:** independently review the final change set, the reconciled #778 body,
all exact-head checks and authority/dependency boundaries. The builder must not merge, close E0 or
start downstream implementation.
