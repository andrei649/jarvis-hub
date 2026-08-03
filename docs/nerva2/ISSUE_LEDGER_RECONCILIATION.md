# Nerva 2.0 E0.3b2c — issue-ledger closure reconciliation

> **Accepted-evidence base:** `main@0c7f880dea1fe254d590ce8967e45cfe453dc52f` on 2026-08-03.  
> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Status:** E0 is `DONE` when the independent integrator accepts this exact transition.

## Purpose

This document pins the issue-body changes that accompany E0 closure. The repository branch carries
the durable target state; the independent integrator updates live #757, #758 and #778 only when the
exact head is accepted, then closes #758. This prevents issue prose from unblocking work before the
repository transition is merged.

## Accepted control evidence

E0 evidence is accepted through #789 (`0c7f880dea1fe254d590ce8967e45cfe453dc52f`). The accepted set
covers baseline, reuse, dependencies, authority, risks, ORIZONT ownership, bounded first issues,
false-closure controls and durable repository/issue ledgers.

## Required issue and repository state after integration

| Source | Required state | Evidence / remaining work |
|---|---|---|
| #757 | E0 done | Records accepted evidence through #789, closes only E0 and names the post-E0 first wave. |
| #758 | E0 done | Closed by the independent integrator after exact-head acceptance; no runtime completion claim. |
| #778 | E0 done | Marks B0 and B1 resolved and M0 complete; keeps B2 partial and B3–B10 open. |
| `BACKLOG.md` | E0 done | Exact marker-bounded block records E0 DONE, post-E0 dependency order and unchanged authority ceilings. |
| `STATUS.md` | E0 done | Exact marker-bounded snapshot records E0 DONE without promoting any first-wave capability to live. |

## Post-E0 first wave

- #780 — E1 Cortex shadow DecisionRecord; no action authority; E0 blocker removed.
- #781 — E2 Atlas identity/provenance and read-only snapshot; E0 blocker removed.
- #782 — E3 episode schema/manual boundaries; #782 still waits for #781.
- #783 — E8 Synapse manifest conformance; descriptions cannot grant permission; E0 blocker removed.
- #784 — E9 benchmark contract/task suite; evaluation cannot change production routing; E0 blocker removed.

#780, #781, #783 and #784 may proceed only after the independent integration decision. #782 still
waits for #781. Issue existence and E0 closure are not implementation evidence.

## Security and honesty invariants

- Ultron / `nerva.action.v1` remains the sole privileged-action authority.
- No runtime, API, persistence, routing, settings or capability-readiness behavior changes here.
- No default-off, seam, reference-driver, hermetic or documentation-only work is promoted to live.
- B2 remains partial and B3–B10 remain open after E0.
- Live task-level mediation, real adapter, owner hardware and release proof remain later gates.

## Integration protocol

1. Review the exact repository diff and all required workflow results.
2. Confirm `scripts/status_sync.py --check`, the ledger migrator and both Nerva checkers pass.
3. Confirm no review concern, dependency conflict or authority drift remains.
4. Merge using the repository's preferred safe method.
5. Update #757, #758 and #778 to the state above and close #758.
6. Remove #758 from #780, #781, #783 and #784; leave only #781 on #782.

## Next smallest slice

**E1.0 / E2.0 / E8.0 / E9.0:** choose one smallest bounded, reuse-first slice per PR. #782 still
waits for #781.
