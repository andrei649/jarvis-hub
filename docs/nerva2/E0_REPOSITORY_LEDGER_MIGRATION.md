# Nerva 2.0 E0 repository-ledger migration

> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Status:** blocker-removal tooling only; E0 remains `VERIFYING` and `close_e0=false`.

## Purpose

`BACKLOG.md` and `STATUS.md` are large historical ledgers. Reconstructing either file from partial
API output risks deleting delivery history, changing unrelated generated content or creating a false
E0 closure claim. `scripts/reconcile_nerva_repository_ledgers.py` provides one bounded and reusable
way to apply the reviewed Nerva blocks from a complete worktree.

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

## Usage in the next slice

Run from a dedicated branch backed by a complete checkout:

```bash
python scripts/reconcile_nerva_repository_ledgers.py --write
python scripts/reconcile_nerva_repository_ledgers.py --check
python scripts/status_sync.py --check
python scripts/check_nerva_roadmap.py
python scripts/check_nerva_e0_completion.py
python -m pytest tests/test_reconcile_nerva_repository_ledgers.py -q
```

Review the resulting `BACKLOG.md` and `STATUS.md` diff before changing the completion manifest or
issue #778. The expected diff is two insertions and zero modifications to historical lines.

## Explicit non-claims

This tooling slice does **not** reconcile either repository ledger by itself, update the #778 body,
close E0, unblock #780–#784 or implement any Nerva runtime capability. Direct ledger edits and the
long-form #778 reconciliation remain the next executable slice. E0 closure remains a separate
independent integrator decision after generated-status checks, both Nerva checkers and all required
exact-head CI are green.
