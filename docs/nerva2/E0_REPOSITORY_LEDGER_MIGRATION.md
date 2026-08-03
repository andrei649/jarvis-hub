# Nerva 2.0 E0 repository-ledger migration

> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Closure transition:** replace only the exact accepted VERIFYING blocks with canonical E0 DONE blocks.

## Purpose

`BACKLOG.md` and `STATUS.md` are large historical ledgers. Reconstructing either file from partial API
output risks deleting delivery history or creating a misleading closure. The repository migrator is
the bounded transition mechanism: it recognizes the exact accepted VERIFYING block from merged #789,
the exact canonical E0 DONE block, or no block at the unique historical anchor. Every other state is
rejected.

## Safety properties

- preserves all bytes outside the marker-bounded block;
- preserves LF or CRLF at the transition site;
- validates both ledgers before writing either one;
- refuses missing, duplicate or ambiguous anchors;
- refuses partial, duplicate and unknown intermediate blocks;
- transitions only the exact accepted VERIFYING block to the canonical E0 DONE block;
- is idempotent after the canonical DONE block is present;
- writes atomically and preserves existing file modes;
- keeps #782 blocked by #781 and keeps Ultron as the sole privileged-action authority.

A partial closure is not accepted by `--check`: if one ledger is DONE and the other still carries the
accepted VERIFYING block, the command fails without writing. `--write` may repair that exact known
state in a dedicated branch after both inputs have been validated.

## Verification commands

```bash
python scripts/reconcile_nerva_repository_ledgers.py --check
python scripts/status_sync.py --check
python scripts/check_nerva_roadmap.py
python scripts/check_nerva_e0_completion.py
pytest -q tests/test_reconcile_nerva_repository_ledgers.py tests/test_nerva_e0_completion.py
```

The focused tests cover LF/CRLF insertion, exact VERIFYING-to-DONE replacement, idempotence, byte
preservation, atomic writes, file-mode preservation and fail-closed behavior for partial, duplicate,
ambiguous and unknown states.

## Non-claims

The closure blocks do not implement any first-wave runtime capability. They do not change APIs,
persistence, routing, settings, permissions or production behavior. Ultron / `nerva.action.v1`
remains the sole privileged-action authority. B2 remains partial and B3–B10 remain open.

## Post-E0 order

After independent integration, #780, #781, #783 and #784 may proceed as separate bounded slices.
#782 still waits for #781. The preferred next movement is **E1.0 / E2.0 / E8.0 / E9.0**, one small
reuse-first PR at a time.
