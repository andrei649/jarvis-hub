# Nerva 2.0 E0.3b2b — issue-ledger verification

> **Snapshot:** `main@25eac3688830750be231c43ebacce889427c50cc` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Machine-readable companion:** [`E0_COMPLETION.json`](E0_COMPLETION.json).  
> **Final reconciliation brief:** [`E0_FINAL_RECONCILIATION.md`](E0_FINAL_RECONCILIATION.md).  
> **Issue-ledger evidence:** [`ISSUE_LEDGER_RECONCILIATION.md`](ISSUE_LEDGER_RECONCILIATION.md).  
> **Status:** E0 is `VERIFYING`; this slice does not close E0 or unblock production implementation.

## 1. Purpose

E0 has accepted baseline, reuse, dependency, authority, risk, ORIZONT ownership and false-closure
controls through #787. This bounded slice reconciles the owner-facing #757 body and the E0 #758 body
without pretending that the large historical repository ledgers or the #778 long-form plan are already
finished.

The remaining gate is **durable ledger agreement**: `BACKLOG.md`, `STATUS.md`, #757, #758 and #778
must describe the same accepted state, and generated-status plus exact-head CI evidence must be green
before an independent integrator can close E0.

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

| Source | Current honest state | Required next change |
|---|---|---|
| `BACKLOG.md` | Contains historical ORIZONT 27–33 delivery and Nerva vision references, but not the accepted current E0 control/first-wave block. | Add one concise current Nerva block naming accepted controls through #787, E0 `VERIFYING`, and #780–#784 as blocked. Preserve historical delivery records. |
| `STATUS.md` | Describes the 1.0 destination and ORIZONT capability program, but not the current E0 verification gate. | Add one current Nerva snapshot with E0 `VERIFYING`, blocked first slices and no live/runtime capability claim. |
| #757 | **Body reconciled.** It now names accepted controls through #787, E0 `VERIFYING` and blocked first slices. | Recheck against the final repository-ledger wording before closure. |
| #758 | **Body reconciled.** It now reports `VERIFYING`, marks first-slice issue creation complete and keeps closure work open. | Close only after repository ledgers, #778 and exact-head evidence agree. |
| #778 | A factual progress update is current; the long-form body still contains historical unchecked items. | Reconcile the body from a complete source in the repository-ledger movement; keep B7/live mediation and later implementation gates open. |

Issue bodies #757 and #758 are reconciled. The #778 body remains pending, as do `BACKLOG.md` and
`STATUS.md`; therefore E0 remains `VERIFYING` and `close_e0=false`.

## 5. E0 closure requirements

E0 may become `DONE` only when all are true:

1. `BACKLOG.md` and `STATUS.md` contain reviewed durable Nerva status blocks.
2. #757, #758 and #778 agree with those repository files.
3. `scripts/status_sync.py --check` and both Nerva integrity checkers pass on the exact head.
4. Full Linux/Windows CI, Security, CodeQL, Smoke, Code Health and park-list checks are green.
5. The direct ledger diff preserves history and does not promote default-off, seam, reference-driver,
   hermetic or documentation-only work to live capability.
6. An independent integrator accepts the evidence and explicitly closes E0.
7. No first-wave production implementation has started ahead of that decision.

## 6. Current bounded slice

The current slice records #787 as accepted control evidence, adds a durable issue-ledger snapshot,
updates #757 and #758 bodies, and extends the repository-only checker so partial issue reconciliation
cannot be mistaken for E0 closure. The checker remains explicit that GitHub issue bodies are external
evidence reviewed by the integrator.

Direct replacement of the large historical `BACKLOG.md` and `STATUS.md` files remains a separate,
reviewable movement inside E0.3b2b. Until that diff, the #778 body reconciliation and all required
checks are present and accepted, E0 remains `VERIFYING`.

The next smallest slice is **E0.3b2b-repository-ledgers — apply the reviewed blocks to `BACKLOG.md`
and `STATUS.md`, reconcile the #778 body, run normal status-generation verification and full CI, then
request an independent E0 closure decision**.
