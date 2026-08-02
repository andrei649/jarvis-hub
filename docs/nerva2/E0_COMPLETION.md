# Nerva 2.0 E0.3b2b — final durable-ledger verification

> **Snapshot:** `main@13290b6a10f2bfce5b10a3bf57305777341c0909` on 2026-08-03.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Machine-readable companion:** [`E0_COMPLETION.json`](E0_COMPLETION.json).  
> **Final reconciliation brief:** [`E0_FINAL_RECONCILIATION.md`](E0_FINAL_RECONCILIATION.md).  
> **Issue-ledger evidence:** [`ISSUE_LEDGER_RECONCILIATION.md`](ISSUE_LEDGER_RECONCILIATION.md).  
> **Repository-ledger evidence:** [`E0_REPOSITORY_LEDGER_MIGRATION.md`](E0_REPOSITORY_LEDGER_MIGRATION.md).  
> **#778 body evidence:** [`E0_778_BODY_RECONCILIATION.md`](E0_778_BODY_RECONCILIATION.md).  
> **Status:** E0 is `VERIFYING`; this slice does not close E0 or unblock production implementation.

## 1. Purpose

E0 has accepted baseline, reuse, dependency, authority, risk, ORIZONT ownership, false-closure and
owner-facing issue-ledger controls through merged #788. Draft #789 applies reviewed current Nerva
blocks to the complete historical `BACKLOG.md` and `STATUS.md` files, refreshes generated project
status through the existing generator and records the complete #778 body reconciliation.

`BACKLOG.md` and `STATUS.md` are reconciled in draft #789. The #778 body is reconciled with an
authoritative current-state snapshot while retaining its B0–B10, M0–M8, metrics and anti-drift plan.
The remaining E0 gate is exact-head independent acceptance. Repository and issue-ledger movement does
not make the first-wave runtime capabilities implemented.

This document is a planning/evidence ledger. It is not a runtime registry, capability catalog or
authority source.

## 2. Accepted E0 control slices

| Slice | Accepted evidence | What it established |
|---|---|---|
| **E0.1** | #771 · `288412086439e5a02c08fcf8e575944c9b81f96c` | Code-pinned baseline and `REUSE / INTEGRATE / BUILD / REFACTOR / RETIRE` decisions. |
| **E0.2** | #772 · `8b8e64d599262f15334ce547b7adfa3c042a7a78` | Acyclic delivery dependencies, contract ownership and the Hybrid Cognition advisory boundary. |
| **E0.3a** | #779 · `ab177c5501eeea379b66d9d33a1ed895a322e934` | Forty evidence-grounded risks, ten stop-ship invariants and closure-evidence rules. |
| **E0.3b1** | #785 · `a943514050a361cbd909761f05c7d9731e0f323e` | ORIZONT 27–33 reuse/ownership reconciliation and bounded first executable issues. |
| **E0.3b2a** | #786 · `265a1c984822b059bfbf9449dacc2bde7554d225` | Durable completion manifest, false-closure guard and ledger-trigger coverage. |
| **E0.3b2b-control** | #787 · `25eac3688830750be231c43ebacce889427c50cc` | Final reconciliation contract, accepted-control pinning and E0 `VERIFYING` controls. |
| **E0.3b2b-issues** | #788 · `13290b6a10f2bfce5b10a3bf57305777341c0909` | Reconciled #757/#758 owner-facing posture and pinned the remaining repository/#778 gates. |

These controls preserve the core boundaries:

- Ultron / `nerva.action.v1` remains the sole privileged-action authority;
- Cortex records/selects routes but cannot authorize or mark completion;
- Atlas exposes immutable state to consumers;
- Episodes writes memory records, not source facts;
- Synapse manifests describe capabilities but never grant permission;
- Research Lab evaluates and recommends but cannot change production routing;
- E12 remains advisory and cannot mutate live state.

## 3. First executable wave

All first-wave issues exist and remain blocked by E0:

| Epic | Issue | Bounded slice | Authority posture |
|---|---:|---|---|
| E1 Cortex | **#780** | Shadow `DecisionRecord` over current routing | `shadow_no_action` |
| E2 Atlas | **#781** | Identity/provenance and read-only snapshot over the current store | `read_only_state` |
| E3 Episodes | **#782** | Episode schema and deterministic manual boundaries | `memory_record_only`; also waits for #781 |
| E8 Synapse | **#783** | Manifest conformance over three existing capabilities | `description_only` |
| E9 Research Lab | **#784** | Versioned benchmark contract and privacy-safe task suite | `evaluation_only` |

No item above is evidence of implementation. The safe post-E0 parallel wave is #780, #781, #783 and
#784; #782 begins only after the minimum Atlas contract in #781.

## 4. Durable-source reconciliation state

| Source | Current honest state | Remaining gate |
|---|---|---|
| `BACKLOG.md` | **Reconciled in draft #789.** One exact marker-bounded block names accepted controls through #788, E0 `VERIFYING`, the blocked first wave and the Ultron authority ceiling. Historical ORIZONT delivery remains outside the insertion. | Independent review and integration of the exact diff. |
| `STATUS.md` | **Reconciled in draft #789.** One exact snapshot records E0 `VERIFYING`, blocked first slices, the authority ceiling and closure checks. Normal generated counters were refreshed from 5,731 to 5,743 collected backend tests. | Independent review and integration of the exact diff. |
| #757 | **Body reconciled.** It names accepted controls through #788, E0 `VERIFYING` and blocked first slices. | Factual draft progress remains external evidence until #789 is accepted. |
| #758 | **Body reconciled.** It reports `VERIFYING`, marks first-slice issue creation complete and keeps closure work open. | Close only after exact-head checks and independent acceptance. |
| #778 | **Body reconciled.** A 2026-08-03 snapshot marks B0 resolved, B1/M0 `VERIFYING`, B2 partial and B3–B10 open while preserving the detailed program plan. | Independent review against this repository evidence. |

Issue bodies #757, #758 and #778 are reconciled. E0 nevertheless remains `VERIFYING` and
`close_e0=false` because only an independent integrator may accept the final exact-head evidence and
close the gate.

## 5. E0 closure requirements

E0 may become `DONE` only when all are true:

1. `BACKLOG.md` and `STATUS.md` contain independently reviewed durable Nerva status blocks.
2. #757, #758 and #778 agree with those repository files.
3. `scripts/status_sync.py --check`, the ledger migrator `--check` and both Nerva integrity checkers
   pass on the exact head.
4. Full Linux/Windows CI, Security, CodeQL, Smoke, Code Health and park-list checks are green.
5. The direct ledger diff preserves history and does not promote default-off, seam, reference-driver,
   hermetic or documentation-only work to live capability.
6. An independent integrator accepts the evidence and explicitly closes E0.
7. No first-wave production implementation has started ahead of that decision.

## 6. Current bounded slice

Draft #789 adds the history-preserving migrator, its focused Linux/Windows tests and workflow coverage;
applies the exact blocks to complete `BACKLOG.md` and `STATUS.md`; refreshes the repository's generated
status artifacts; upgrades the E0 checker to exact canonical-block validation; and reconciles the full
#778 body without deleting its detailed blocker and milestone plan.

The one-shot branch workflow used only locked dependencies and `contents: write`, enforced a strict
allowlist, verified both marker pairs and removed itself in the generated commit. The #778 body edit is
external issue evidence mirrored by `E0_778_BODY_RECONCILIATION.md`. No runtime, API, persistence,
routing, settings, capability-readiness or privileged-action behavior changed.

The next smallest slice is **E0.3b2b-independent-closure — independently review draft #789, the
reconciled #778 body, all final exact-head generated-status, ledger, Nerva and workflow evidence,
dependency order and authority boundaries. The builder must not merge, close E0 or begin #780–#784**.
