# Nerva 2.0 E0.3b2b — issue-ledger reconciliation

> **Snapshot:** `main@13290b6a10f2bfce5b10a3bf57305777341c0909` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Status:** E0 remains `VERIFYING`; `close_e0=false`.

## Purpose

Merged #788 reconciled the owner-facing master body (#757) and E0 epic body (#758) with accepted E0
evidence. Draft #789 now reconciles the complete repository ledgers while keeping the still-unmodified
#778 long-form body explicit.

This document is planning evidence only. It does not implement Cortex, Atlas, Episodes, Synapse SDK
or Research Lab, and it does not change runtime behavior or privileged-action authority.

## Accepted control evidence

| Slice | PR | Accepted merge | Result |
|---|---:|---|---|
| E0.1 | #771 | `288412086439e5a02c08fcf8e575944c9b81f96c` | code-pinned baseline and migration decisions |
| E0.2 | #772 | `8b8e64d599262f15334ce547b7adfa3c042a7a78` | dependency DAG, contracts and authority ownership |
| E0.3a | #779 | `ab177c5501eeea379b66d9d33a1ed895a322e934` | risk register and stop-ship invariants |
| E0.3b1 | #785 | `a943514050a361cbd909761f05c7d9731e0f323e` | ORIZONT ownership map and first executable issues |
| E0.3b2a | #786 | `265a1c984822b059bfbf9449dacc2bde7554d225` | durable completion manifest and false-closure guard |
| E0.3b2b-control | #787 | `25eac3688830750be231c43ebacce889427c50cc` | final reconciliation contract and VERIFYING controls |
| E0.3b2b-issues | #788 | `13290b6a10f2bfce5b10a3bf57305777341c0909` | #757/#758 body reconciliation and remaining-gate pinning |

## Issue and repository-ledger state

| Source | State after this slice | Evidence / remaining work |
|---|---|---|
| #757 | body reconciled | Names E0 `VERIFYING`, accepted controls through #788 and blocked first slices #780–#784. A factual draft update is added without claiming integration. |
| #758 | body reconciled | Marks first-slice issue creation complete, records accepted controls and keeps #778 plus independent closure open. |
| #778 | progress current; body reconciliation pending | Factual comments record accepted controls and draft #789. The complete long-form body must be edited from a full source without deleting its blocker plan. |
| `BACKLOG.md` | reconciled in draft #789 | One exact block records E0 `VERIFYING`, first-wave dependencies and the Ultron authority ceiling while preserving historical ORIZONT delivery. |
| `STATUS.md` | reconciled in draft #789 | One exact snapshot records the verification gate; generated project counters were refreshed through `scripts/status_sync.py`. |

## First executable wave remains blocked

- #780 — E1 Cortex shadow DecisionRecord; no action authority.
- #781 — E2 Atlas identity/provenance and read-only snapshot; no live-state mutation.
- #782 — E3 episode schema/manual boundaries; memory-record-only and additionally blocked by #781.
- #783 — E8 Synapse manifest conformance; descriptions cannot grant permission.
- #784 — E9 benchmark contract/task suite; evaluation cannot change production routing.

Issue existence is not implementation evidence. #780, #781, #783 and #784 may start only after an
independent E0 closure decision; #782 still waits for #781.

## Security and honesty invariants

- Ultron / `nerva.action.v1` remains the sole privileged-action authority.
- No runtime, API, persistence, routing, settings or capability-readiness behavior changes here.
- No default-off, seam, reference-driver, hermetic or documentation-only work is promoted to live.
- Live task-level mediation proof, owner hardware proof and release proof remain later gates.

## Next smallest slice

**E0.3b2b-778-body:** reconcile the complete #778 long-form body without deleting its detailed program
plan, run `scripts/status_sync.py --check`, the ledger migrator `--check`, both Nerva integrity checkers
and all required exact-head CI, then request a separate independent E0 closure decision.
