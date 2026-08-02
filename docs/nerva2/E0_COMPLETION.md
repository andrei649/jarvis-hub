# Nerva 2.0 E0.3b2a — durable completion ledger

> **Snapshot:** `main@a943514050a361cbd909761f05c7d9731e0f323e` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Machine-readable companion:** [`E0_COMPLETION.json`](E0_COMPLETION.json).  
> **Status:** E0 remains `BUILDING`; this slice does not close E0 or unblock production implementation.

## 1. Purpose

E0 now has accepted baseline, reuse, dependency, authority, risk and ORIZONT ownership artifacts.
The remaining risk is not missing architecture; it is **ledger drift**. `BACKLOG.md`, `STATUS.md`,
#757, #758 and #778 must describe the same accepted state before E1/E2/E3/E8/E9 implementation
starts.

This document is a bounded completion ledger. It records what has been accepted and the exact work
still required. It does not become another runtime registry, capability catalog or authority source.

## 2. Accepted E0 control slices

| Slice | Accepted evidence | What it established |
|---|---|---|
| **E0.1** | #771 · `288412086439e5a02c08fcf8e575944c9b81f96c` | Code-pinned baseline and `REUSE / INTEGRATE / BUILD / REFACTOR / RETIRE` decisions. |
| **E0.2** | #772 · `8b8e64d599262f15334ce547b7adfa3c042a7a78` | Acyclic delivery dependencies, contract ownership and the Hybrid Cognition advisory boundary. |
| **E0.3a** | #779 · `ab177c5501eeea379b66d9d33a1ed895a322e934` | Forty evidence-grounded risks, ten stop-ship invariants and closure-evidence rules. |
| **E0.3b1** | #785 · `a943514050a361cbd909761f05c7d9731e0f323e` | ORIZONT 27–33 reuse/ownership reconciliation and bounded first executable issues. |

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
| `BACKLOG.md` | Contains the legacy ORIZONT 27–33 roadmap and Nerva vision references, but not the accepted current E0 control ledger/first-wave issue block. | Add one concise current Nerva block linking the accepted artifacts and #780–#784. Preserve historical ORIZONT rows and their original delivery evidence. |
| `STATUS.md` | Describes the 1.0 destination and ORIZONT capability program, but does not yet expose the current E0 `BUILDING` state and accepted first-wave blockers. | Add one current Nerva snapshot: accepted controls, E0 still `BUILDING`, #780–#784 blocked and no live/runtime capability claim. |
| #757 | Dependency order is current; durable first-wave/status block still needs final reconciliation. | Record E0.1–E0.3b1 acceptance and #780–#784 as blocked first slices. |
| #758 | Correctly remains `BUILDING`; deliverable checkboxes/status need final E0.3b reconciliation. | Mark first-slice creation complete only after durable repository ledgers agree; close only by integrator decision. |
| #778 | Contains the end-state and blocker plan, but older checklist items still read as unlanded. | Mark accepted control work factually and keep live Ultron mediation, continuity mapping and program-manifest work open. |

## 5. E0 closure requirements

E0 may become `DONE` only when all are true:

1. `BACKLOG.md` and `STATUS.md` contain reviewed durable Nerva status blocks.
2. #757, #758 and #778 agree with those repository files.
3. The normal status generator/check and all required CI workflows are green on the exact head.
4. The direct ledger diff preserves legacy history and does not promote default-off, seam, reference-
   driver, hermetic or documentation-only work to live capability.
5. An independent integrator accepts the evidence and explicitly closes E0.
6. No first-wave production implementation has started ahead of that decision.

## 6. Why this slice stops here

Direct replacement of the large historical `BACKLOG.md` and `STATUS.md` files is a separate reviewable
movement. Combining the completion model, issue-body reconciliation and large generated/historical
ledger edits would make a documentation-only gate harder to review and easier to mis-merge.

The next smallest slice is **E0.3b2b — direct `BACKLOG.md` / `STATUS.md` reconciliation, normal
status-generation verification and independent E0 closure decision**.
