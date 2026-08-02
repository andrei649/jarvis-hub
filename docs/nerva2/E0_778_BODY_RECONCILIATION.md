# Nerva 2.0 E0.3b2b — blocker-plan body reconciliation

> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Delivery PR:** #789.  
> **Status:** E0 remains `VERIFYING`; `close_e0=false`.

## Purpose

Issue #778 is the long-lived cross-epic blocker and milestone plan for Nerva 2.0. Its detailed B0–B10,
M0–M8, metrics and anti-drift sections remain valuable, but the body predated accepted E0 controls and
therefore contained stale unchecked work for already accepted slices.

The 2026-08-03 reconciliation adds one authoritative current-state snapshot to the complete issue body
without deleting or compressing the detailed plan. The snapshot distinguishes accepted E0 control
evidence from later whole-program work and keeps all implementation and authority ceilings explicit.

## Current blocker-plan posture

- **B0 is resolved:** #772 accepted the acyclic delivery DAG, the exact E5 blocker set, the separate
  runtime-feedback graph and the advisory-only E12 boundary.
- **B1 / M0 remain `VERIFYING`:** controls #771, #772, #779, #785, #786, #787 and #788 are accepted;
  the repository-ledger reconciliation and generated-status refresh are present. E0 is not closed
  until independent exact-head acceptance.
- **B2 is partial:** repository manifests and checkers now protect the accepted E0 and first-wave
  contract, but the broader whole-program manifest/orphan checker remains future work.
- **B3–B10 remain open:** Continuity Core mapping, universal cognitive-ledger contracts, SDK breadth,
  real actuation, live task-level Ultron mediation, research/calibration, Night Shift prerequisites and
  product proof are not promoted to E0 completion.
- **First-wave issues remain blocked:** #780, #781, #783 and #784 wait for #758; #782 waits for #758
  and #781.
- **Authority remains unchanged:** Ultron / `nerva.action.v1` is the sole privileged-action authority.

The reconciliation snapshot explicitly supersedes stale checkbox state only for the current status of
B0, B1 and M0. The detailed work breakdown remains intact as historical and future planning context.

## Preserved truth boundaries

- Issue creation, documentation and hermetic checks are not runtime implementation evidence.
- No first-wave capability is marked live or complete.
- No default-off seam, reference driver or generated status is promoted to real-world proof.
- Live task-level mediation, owner hardware and release evidence remain later gates.
- The builder does not close E0 or start downstream implementation.

## Repository evidence

- exact marker-bounded blocks in `BACKLOG.md` and `STATUS.md`;
- generated status synchronized through `scripts/status_sync.py`;
- a fail-closed, history-preserving ledger migrator and focused LF/CRLF tests;
- accepted controls through merged #788 in `E0_COMPLETION.json`;
- permanent Nerva Roadmap Integrity coverage for the ledger migrator and E0 checker;
- this document as the durable repository record of the #778 body reconciliation.

## Verification

```bash
python scripts/status_sync.py --check
python scripts/reconcile_nerva_repository_ledgers.py --check
python scripts/check_nerva_roadmap.py
python scripts/check_nerva_e0_completion.py
python -m pytest tests/test_reconcile_nerva_repository_ledgers.py -q
```

All required exact-head workflow families must be green after this reconciliation commit. The issue
body itself remains external GitHub evidence and requires independent review against this repository
record.

## Next smallest slice

**E0.3b2b-independent-closure:** independently review the final change set, the reconciled #778 body,
all exact-head checks, dependency order and authority boundaries. Only an independent integrator may
change E0 from `VERIFYING` to `DONE`; the builder must not merge or begin #780–#784.
