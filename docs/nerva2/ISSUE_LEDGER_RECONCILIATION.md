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

## 2026-09-06 — B2 live issue-ledger reconciliation (program control)

> **Accepted-evidence base:** `main@c16d84e989ffd26ea941e02ae8ae49750d7dd8ca` (v1.0.0).
> **Status:** reconciled in the repository; **live issue state not verified in this build**
> (no `gh` in the build environment — the checker reports `not_verified`, never `verified`, without a real run).

### What changed in the manifest

| Item | Before | After | Evidence |
|---|---|---|---|
| `movement_gate.enforcement_state` | `required` while CI no longer ran any movement checker | `safety_disabled` with a `rollback` record bound to PR #981 / `824ff187` (`rollback_of_issue=846`) | [`NERVA_ISSUE_MOVEMENT_V1.md`](NERVA_ISSUE_MOVEMENT_V1.md) "Forward rollback" |
| `movement_gate.registry` | five paths deleted in `824ff187` still registered (`nerva-roadmap.yml`, both movement/manifest checkers and their tests) | four paths moved to `registry_retired` (checker errors if any reappears outside the registry); `scripts/check_nerva_program_manifest.py` restored as a compact advisory checker; new control files appended | `scripts/check_nerva_program_manifest.py`, `.github/workflows/nerva-manifest-check.yml` |
| E11 `owner_live` blocker | `owner_live_proof_missing` on `RISKS.md` | `a1_section0_run_record_owed` on `docs/MANUAL_TESTING.md` — A8 cleared by the owner 2026-08-28 (good feedback); the post-tag A1 §0 run record is the remaining owner-live item | `BACKLOG.md` A8 row, `docs/HISTORY.md` 2026-09-01 |
| E5 / E8 `program_gate` B7 | reason only | same reason plus a note: PR #918 (merge `b5e52c6`) RETAINED on `main` 2026-09-01, default-off, **merged but not program-accepted** | `docs/HISTORY.md` 2026-09-01 |
| E4 references | #762 only | + #1008 (Jarvis's own Identity Manifest, identity-boundary lane; #762 stays Howard-only) | [`CONTINUITY_CORE_RECONCILIATION.md`](CONTINUITY_CORE_RECONCILIATION.md) |
| E5 program status | `not_started` / `blocked` | `building` / `in_progress` (derived) — `nerva.work-run.v1` is `candidate` on the E5.0 slice; every E5 delivery gate and the B7 program gate stay open | [`CONTRACT_REGISTRY.json`](CONTRACT_REGISTRY.json), `NIGHT_SHIFT_E5_0.md` |
| `contract_registry` mirror | absent | statuses + SHA-256 of `CONTRACT_REGISTRY.json`; the checker fails on drift | checker `_check_contracts` |

### Live issue state the manifest expects (to be verified by `--live`)

| Issue | Expected | Basis |
|---|---|---|
| #757 program, #778 blocker plan | exist (open) | program still open; B2 partial |
| #758 E0 epic | `CLOSED` | E0 `done` |
| #759–#769, #773 epics | `OPEN` | streams not `done` |
| #839, #846, #847 | exist | manifest / bootstrap / manual-integration control issues; state not asserted |
| #818 (B7), #841, #844, #1008 | exist | typed-blocker and reference issues |

The checker's `--live` mode queries `gh issue view <n> --repo andrei649/jarvis-hub --json number,state,title`
for each row, reports `verified` only when every query succeeded and every expectation held,
`mismatch` with the differing issues otherwise, and `not_verified` when `gh` is missing or any
query fails. It never edits the manifest and never sets `live_issue_state_verified_by_checker`
to `true` in the file; that field is a fixed `false` by design (checker error otherwise).

### Integration protocol (advisory lane)

1. Run `python scripts/check_nerva_program_manifest.py` offline; it must print `OK`.
2. After merge, the `Nerva Manifest Check` workflow runs on `main` and weekly; its `--live` step is
   advisory and lands in the job summary. A `mismatch` is a ledger task, not a merge blocker
   (AGENTS.md posture, owner decision 2026-08-29).
3. Record the first real `verified` / `mismatch` outcome here with the run URL; until then this
   section stays **not verified**.
