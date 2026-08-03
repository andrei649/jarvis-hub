# Nerva 2.0 E0.3b2c — closure state transition

> **Accepted-evidence base:** `main@0c7f880dea1fe254d590ce8967e45cfe453dc52f` on 2026-08-03.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Machine-readable companion:** [`E0_COMPLETION.json`](E0_COMPLETION.json).  
> **Status:** E0 is `DONE` when this exact transition is independently integrated; `close_e0=true`.

## 1. Decision

E0 has independently accepted evidence for the component baseline, reuse/build/retire map, dependency
DAG, contract ownership, privileged-action boundary, risk register, ORIZONT ownership map, bounded
first issues, durable issue ledgers and durable repository ledgers. The final accepted control is #789,
merged as `0c7f880dea1fe254d590ce8967e45cfe453dc52f`.

This closure changes only planning/control truth. It does not implement Cortex, Atlas, Episodes,
Synapse SDK or Research Lab; it does not promote a seam, default-off route, reference driver,
hermetic test or documentation claim to a live capability.

## 2. Accepted E0 control slices

| Slice | Accepted evidence | What it established |
|---|---|---|
| **E0.1** | #771 · `288412086439e5a02c08fcf8e575944c9b81f96c` | Code-pinned baseline and reuse/build/retire decisions. |
| **E0.2** | #772 · `8b8e64d599262f15334ce547b7adfa3c042a7a78` | Acyclic dependencies, interface ownership and advisory-only feedback boundaries. |
| **E0.3a** | #779 · `ab177c5501eeea379b66d9d33a1ed895a322e934` | Evidence-grounded risks and stop-ship invariants. |
| **E0.3b1** | #785 · `a943514050a361cbd909761f05c7d9731e0f323e` | ORIZONT 27–33 reuse/ownership mapping and bounded first issues. |
| **E0.3b2a** | #786 · `265a1c984822b059bfbf9449dacc2bde7554d225` | Machine-readable completion ledger and false-closure guard. |
| **E0.3b2b-control** | #787 · `25eac3688830750be231c43ebacce889427c50cc` | Final reconciliation contract and verification controls. |
| **E0.3b2b-issues** | #788 · `13290b6a10f2bfce5b10a3bf57305777341c0909` | Reconciled owner-facing issue posture. |
| **E0.3b2b-repository-ledgers** | #789 · `0c7f880dea1fe254d590ce8967e45cfe453dc52f` | History-preserving `BACKLOG.md`, `STATUS.md` and #778 reconciliation with permanent guards. |

## 3. Authority boundaries remain unchanged

- Ultron / `nerva.action.v1` remains the sole privileged-action authority.
- Cortex may create shadow decisions but cannot authorize, execute or mark completion.
- Atlas exposes read-only state to first-wave consumers and does not create a second truth store.
- Episodes writes memory records and cannot overwrite source facts.
- Synapse manifests describe permissions; they never grant them.
- Research Lab evaluates candidates and cannot change production routing.
- Howard and E12 remain advisory and cannot substitute prediction for consent.

## 4. First executable wave after E0

| Epic | Issue | Bounded slice | Remaining blockers | Authority posture |
|---|---:|---|---|---|
| E1 Cortex | **#780** | Shadow `DecisionRecord` over current routing | none | `shadow_no_action` |
| E2 Atlas | **#781** | Identity/provenance and read-only snapshot | none | `read_only_state` |
| E3 Episodes | **#782** | Episode schema and deterministic manual boundaries | **#781** | `memory_record_only` |
| E8 Synapse | **#783** | Manifest conformance over three existing capabilities | none | `description_only` |
| E9 Research Lab | **#784** | Versioned benchmark contract and privacy-safe task suite | none | `evaluation_only` |

No item above is evidence of implementation. #780, #781, #783 and #784 may proceed in separate,
bounded PRs after independent integration of this closure. #782 still waits for #781.

## 5. Fail-closed closure mechanics

The closure is intentionally indivisible:

1. `status=done` and `close_e0=true` must change together.
2. The accepted-control set must include #789.
3. `BACKLOG.md` and `STATUS.md` must both contain their exact canonical E0 DONE blocks.
4. The roadmap and completion manifests must remove #758 from all first-wave blockers.
5. #782 must retain #781 as its only blocker.
6. All authority ceilings and non-claims must remain present.
7. #757, #758 and #778 are updated by the independent integrator when the transition is accepted.

The ledger migrator recognizes only the exact accepted VERIFYING blocks from #789 or the exact new
DONE blocks. Any unknown, duplicated or partial state fails. It validates both ledgers before writing
either. Unit tests also mutate the completion manifest to prove partial closure is rejected.

## 6. Verification required on the exact head

- `python scripts/reconcile_nerva_repository_ledgers.py --check`
- `python scripts/check_nerva_roadmap.py`
- `python scripts/check_nerva_e0_completion.py`
- `python scripts/status_sync.py --check`
- focused closure and migrator tests on Linux and Windows
- full repository CI, Security, CodeQL, Smoke Test, Code Health and park-list workflows
- independent diff, dependency, issue-body and authority review

## 7. Work that remains open after E0

E0 completion does not close the Nerva program. B2 whole-program manifest/orphan checking remains
partial. B3–B10 remain open, including Continuity Core mapping, universal cognitive-ledger contracts,
SDK breadth, real actuation, restart-safe task-level Ultron mediation, research/calibration, Night
Shift prerequisites, owner-hardware proof and the Nerva 2.0 release gate.

## 8. Next smallest slice

**E1.0 / E2.0 / E8.0 / E9.0:** choose one smallest bounded slice per PR. The preferred first movement
is the contract-only or read-only work that maximizes reuse and creates no privileged effect. #780,
#781, #783 and #784 may proceed independently; #782 still waits for #781.
