# Nerva 2.0 E0.3b2b — repository-ledger verification

> **Snapshot:** `main@13290b6a10f2bfce5b10a3bf57305777341c0909` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Machine-readable companion:** [`E0_COMPLETION.json`](E0_COMPLETION.json).  
> **Final reconciliation brief:** [`E0_FINAL_RECONCILIATION.md`](E0_FINAL_RECONCILIATION.md).  
> **Issue-ledger evidence:** [`ISSUE_LEDGER_RECONCILIATION.md`](ISSUE_LEDGER_RECONCILIATION.md).  
> **Repository-ledger evidence:** [`E0_REPOSITORY_LEDGER_MIGRATION.md`](E0_REPOSITORY_LEDGER_MIGRATION.md).  
> **Status:** E0 is `VERIFYING`; this slice does not close E0 or unblock production implementation.

## 1. Purpose

E0 has accepted baseline, reuse, dependency, authority, risk, ORIZONT ownership, false-closure and
owner-facing issue-ledger controls through merged #788. Draft #789 applies the reviewed current Nerva
blocks to the complete historical `BACKLOG.md` and `STATUS.md` files and refreshes generated project
status through the repository's existing generator.

`BACKLOG.md` and `STATUS.md` are reconciled in draft #789. The remaining durable-source blocker is the
complete #778 long-form body, followed by exact-head CI and an independent closure decision. The
repository-ledger movement does not make the first-wave runtime capabilities implemented.

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
| #757 | **Body reconciled.** It names accepted controls through #788, E0 `VERIFYING` and blocked first slices. | Add factual draft progress; change durable body only when accepted state changes. |
| #758 | **Body reconciled.** It reports `VERIFYING`, marks first-slice issue creation complete and keeps closure work open. | Close only after #778, exact-head checks and independent acceptance. |
| #778 | Factual progress comments are current; the long-form body still contains historical unchecked items. | Reconcile the complete body without deleting the blocker plan or promoting later gates to E0 completion. |

Issue bodies #757 and #758 are reconciled. The #778 body remains pending; therefore E0 remains
`VERIFYING` and `close_e0=false` even though both repository ledgers are now present in the draft.

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
status artifacts; and upgrades the E0 checker from a pending-ledger guard to exact canonical-block
validation.

The one-shot branch workflow used only locked dependencies and `contents: write`, enforced a strict
allowlist, verified both marker pairs and removed itself in the generated commit. It introduced no
runtime, API, persistence, routing, settings, capability-readiness or privileged-action behavior.

The next smallest slice is **E0.3b2b-778-body — reconcile the complete #778 long-form body without
deleting its program plan, then run exact-head generated-status, ledger, Nerva and full CI checks and
request a separate independent E0 closure review**.
