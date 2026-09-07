# Nerva program manifest v1

> Offline repository evidence snapshot rendered by `scripts/check_nerva_program_manifest.py`. This document does not query live GitHub, does not authorize execution, does not declare program completion, and does not establish release readiness.

- The JSON manifest is the sole current dependency/status/gate/blocker/runtime truth; this view is regenerated with `--write` and byte-checked on every checker run.
- Evidence baseline: `c16d84e989ffd26ea941e02ae8ae49750d7dd8ca`
- Observed at (mutable snapshot context): `2026-09-06T10:19:43Z`
- Program issue: [#757](https://github.com/andrei649/jarvis-hub/issues/757)
- Blocker plan: [#778](https://github.com/andrei649/jarvis-hub/issues/778)
- Manifest control: [#839](https://github.com/andrei649/jarvis-hub/issues/839)
- Live issue state verified by this file: `false` (a `--live` checker run reports `verified` / `mismatch` / `not_verified` in its own report only)

## Issue movement gate

- Schema version: `1`
- Enforcement state: `safety_disabled`
- Historical bootstrap source: `843918848c11bbd3f0099f9504d0e0eaaa56b9d6`
- Accepted implementation base: `e596920ec60f19d2e7f0937819c892746a1c42b2`
- Program-control issues: [#846](https://github.com/andrei649/jarvis-hub/issues/846)
- Program-control pull requests: [#981](https://github.com/andrei649/jarvis-hub/pull/981)
- Rollback record: forward safety movement of #846 bound to [#981](https://github.com/andrei649/jarvis-hub/pull/981) (`824ff18749630e3ee6a6d6bfd5b4d362b1d388f6`) — Owner de-gate decision 2026-08-28/29 (#981): the PR-blocking Nerva movement and roadmap checkers were deleted from CI before this forward-rollback record was written; the record is reconciled after the fact (2026-09-06) and the manifest checker returns as an advisory post-merge/scheduled job.
- Receipt proof mode: `point_in_time`; continuous currentness: `false`
- Manual-integration guard: [#847](https://github.com/andrei649/jarvis-hub/issues/847) pins `.github/workflows/pr-auto-merge.yml` and `tests/test_pr_auto_merge_policy.py`.
- This gate has no GitHub-write, runtime, completion, or release authority.

### Registry (every path must exist)

- `.github/workflows/ci.yml`
- `.github/workflows/nerva-manifest-check.yml`
- `.github/workflows/pr-auto-merge.yml`
- `BACKLOG.md`
- `GO_LIVE_PLAN.md`
- `NERVA.md`
- `README.md`
- `STATUS.md`
- `docs/nerva2/CONTRACT_REGISTRY.json`
- `docs/nerva2/INTEGRATION_CATALOGUE_ADOPTION_PASS_PLAYWRIGHT.md`
- `docs/nerva2/ISSUE_LEDGER_RECONCILIATION.md`
- `docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md`
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json`
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md`
- `docs/superpowers/plans/2026-08-07-b2-live-issue-ledger.md`
- `docs/superpowers/specs/2026-08-07-b2-live-issue-ledger-design.md`
- `project-status.json`
- `scripts/check_nerva_program_manifest.py`
- `tests/test_nerva_program_manifest_checker.py`
- `tests/test_pr_auto_merge_policy.py`

### Retired registry paths (must stay absent)

| Path | Retired in | Pull request |
|---|---|---:|
| `.github/workflows/nerva-roadmap.yml` | `824ff1874963` | [#981](https://github.com/andrei649/jarvis-hub/pull/981) |
| `scripts/check_nerva_issue_movement.py` | `824ff1874963` | [#981](https://github.com/andrei649/jarvis-hub/pull/981) |
| `tests/test_nerva_issue_movement.py` | `824ff1874963` | [#981](https://github.com/andrei649/jarvis-hub/pull/981) |
| `tests/test_nerva_program_manifest.py` | `824ff1874963` | [#981](https://github.com/andrei649/jarvis-hub/pull/981) |

## Program status and derived delivery eligibility

| Stream | Epic | Program status | Delivery eligibility | Completion evidence |
|---|---:|---|---|---|
| E0 — Baseline and migration map | [#758](https://github.com/andrei649/jarvis-hub/issues/758) | `done` | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E1 — Cortex meta-decision and capability routing | [#759](https://github.com/andrei649/jarvis-hub/issues/759) | `building` | `in_progress` | — |
| E2 — Atlas unified reality graph | [#760](https://github.com/andrei649/jarvis-hub/issues/760) | `building` | `in_progress` | — |
| E3 — Episodes experience-centric memory | [#761](https://github.com/andrei649/jarvis-hub/issues/761) | `building` | `in_progress` | — |
| E4 — Howard digital twin and preference model | [#762](https://github.com/andrei649/jarvis-hub/issues/762) | `not_started` | `blocked` | — |
| E5 — Night Shift autonomous work loop | [#763](https://github.com/andrei649/jarvis-hub/issues/763) | `building` | `in_progress` | — |
| E6 — Reflection and memory consolidation | [#764](https://github.com/andrei649/jarvis-hub/issues/764) | `building` | `in_progress` | — |
| E7 — Governed world model and what-if simulation | [#765](https://github.com/andrei649/jarvis-hub/issues/765) | `not_started` | `blocked` | — |
| E8 — Synapse Skills SDK and acquisition loop | [#766](https://github.com/andrei649/jarvis-hub/issues/766) | `building` | `in_progress` | — |
| E9 — Research Lab and continuous benchmark harness | [#767](https://github.com/andrei649/jarvis-hub/issues/767) | `building` | `in_progress` | — |
| E10 — Executive dashboard and coherent experience | [#768](https://github.com/andrei649/jarvis-hub/issues/768) | `not_started` | `blocked` | — |
| E11 — Proof, safety and release gate | [#769](https://github.com/andrei649/jarvis-hub/issues/769) | `not_started` | `blocked` | — |
| E12 — Hybrid Cognition Lab | [#773](https://github.com/andrei649/jarvis-hub/issues/773) | `discovery` | `in_progress` | — |

Program status describes the reviewed work snapshot. Delivery eligibility is derived independently: active discovery/build/verification remains `in_progress`; a consumer-specific gate may be satisfied while its source epic is still building.

| Program status | Open delivery gate or typed blocker | Derived result |
|---|---|---|
| `not_started` | no | `eligible` |
| `not_started` | yes | `blocked` |
| `discovery`, `building`, or `verifying` | either | `in_progress` |
| `blocked` | yes | `blocked` (no open cause is invalid) |
| `done` | no | `satisfied` (an open cause is invalid) |

## Delivery gates

| Consumer | Source | Gate state | Commit and evidence context |
|---|---|---|---|
| E1 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E2 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E3 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E3 | E2 | `satisfied` | [`9a13a0241fb65d01809f539f1048944ea01a3bf5`](https://github.com/andrei649/jarvis-hub/commit/9a13a0241fb65d01809f539f1048944ea01a3bf5) (immutable commit) · [#781](https://github.com/andrei649/jarvis-hub/issues/781) (mutable context) · [#795](https://github.com/andrei649/jarvis-hub/pull/795) (mutable context) · [`docs/nerva2/ATLAS_E2_0.md` at `9a13a0241fb6`](https://github.com/andrei649/jarvis-hub/blob/9a13a0241fb65d01809f539f1048944ea01a3bf5/docs/nerva2/ATLAS_E2_0.md) (immutable blob locator) · `atlas_minimum_for_episodes_accepted` |
| E4 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E4 | E3 | `unsatisfied` | — |
| E5 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E5 | E1 | `unsatisfied` | — |
| E5 | E2 | `unsatisfied` | — |
| E5 | E3 | `unsatisfied` | — |
| E5 | E6 | `unsatisfied` | — |
| E6 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E6 | E3 | `satisfied` | [`a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f`](https://github.com/andrei649/jarvis-hub/commit/a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f) (immutable commit) · [#806](https://github.com/andrei649/jarvis-hub/issues/806) (mutable context) · [#823](https://github.com/andrei649/jarvis-hub/pull/823) (mutable context) · [`docs/nerva2/REFLECTION_E6_0.md` at `a33c9a5db5cc`](https://github.com/andrei649/jarvis-hub/blob/a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f/docs/nerva2/REFLECTION_E6_0.md) (immutable blob locator) · `episodes_minimum_for_reflection_accepted` |
| E7 | E1 | `unsatisfied` | — |
| E7 | E2 | `unsatisfied` | — |
| E7 | E3 | `unsatisfied` | — |
| E7 | E4 | `unsatisfied` | — |
| E8 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E9 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E10 | E1 | `unsatisfied` | — |
| E10 | E2 | `unsatisfied` | — |
| E10 | E5 | `unsatisfied` | — |
| E10 | E6 | `unsatisfied` | — |
| E11 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E11 | E1 | `unsatisfied` | — |
| E11 | E2 | `unsatisfied` | — |
| E11 | E3 | `unsatisfied` | — |
| E11 | E4 | `unsatisfied` | — |
| E11 | E5 | `unsatisfied` | — |
| E11 | E6 | `unsatisfied` | — |
| E11 | E7 | `unsatisfied` | — |
| E11 | E8 | `unsatisfied` | — |
| E11 | E9 | `unsatisfied` | — |
| E11 | E10 | `unsatisfied` | — |
| E11 | E12 | `unsatisfied` | — |
| E12 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · `e0_control_gate_accepted` |
| E12 | E1 | `unsatisfied` | — |
| E12 | E2 | `unsatisfied` | — |
| E12 | E3 | `unsatisfied` | — |
| E12 | E6 | `unsatisfied` | — |
| E12 | E9 | `unsatisfied` | — |

A satisfied delivery edge requires an accepted 40-hex commit, an artifact present at that commit, and mutable issue/PR context. An upstream epic's overall status is never substituted for consumer-specific gate acceptance.

## Typed blockers

| Stream | Kind | Target | Evidence context | Reason code | Note |
|---|---|---|---|---|---|
| E4 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E5 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E5 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E5 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E5 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E5 | `program_gate` | `B7` | [#818](https://github.com/andrei649/jarvis-hub/issues/818) · [`BACKLOG.md`](../../BACKLOG.md) | `task_mediation_acceptance_pending` | PR #918 (merge b5e52c6, reviewed source 6eed5a7) RETAINED on main by owner decision 2026-09-01, default-off; merged but not program-accepted, so this gate stays open until #906 is provisioned or re-scoped. |
| E7 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E7 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E7 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E7 | `delivery_gate` | `E4` | [#762](https://github.com/andrei649/jarvis-hub/issues/762) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E8 | `external_dependency` | `PROVIDER_E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/RESEARCH_LAB_E9_1.md`](../../docs/nerva2/RESEARCH_LAB_E9_1.md) | `provider_specific_evidence_missing` | — |
| E8 | `program_gate` | `B7` | [#818](https://github.com/andrei649/jarvis-hub/issues/818) · [`BACKLOG.md`](../../BACKLOG.md) | `task_mediation_acceptance_pending` | PR #918 (merge b5e52c6, reviewed source 6eed5a7) RETAINED on main by owner decision 2026-09-01, default-off; merged but not program-accepted, so this gate stays open until #906 is provisioned or re-scoped. |
| E10 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E10 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E10 | `delivery_gate` | `E5` | [#763](https://github.com/andrei649/jarvis-hub/issues/763) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E10 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E10` | [#768](https://github.com/andrei649/jarvis-hub/issues/768) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E12` | [#773](https://github.com/andrei649/jarvis-hub/issues/773) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E4` | [#762](https://github.com/andrei649/jarvis-hub/issues/762) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E5` | [#763](https://github.com/andrei649/jarvis-hub/issues/763) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E7` | [#765](https://github.com/andrei649/jarvis-hub/issues/765) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E8` | [#766](https://github.com/andrei649/jarvis-hub/issues/766) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `delivery_gate` | `E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E11 | `owner_live` | `OWNER_LIVE` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/MANUAL_TESTING.md`](../../docs/MANUAL_TESTING.md) | `a1_section0_run_record_owed` | A8 owner-host proof cleared by the owner on 2026-08-28 (good feedback); the remaining owner-live item is the post-tag A1 MANUAL_TESTING section 0 run record, still owed. |
| E11 | `program_gate` | `RECURRING_WORKFLOWS` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/nerva2/RISKS.md`](../../docs/nerva2/RISKS.md) | `recurring_workflow_proof_missing` | — |
| E11 | `program_gate` | `RESTORE_SOAK` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/nerva2/RISKS.md`](../../docs/nerva2/RISKS.md) | `restore_soak_proof_missing` | — |
| E12 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E12 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E12 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E12 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |
| E12 | `delivery_gate` | `E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | `upstream_gate_not_accepted` | — |

## Runtime feedback — advisory only

| Source | Consumer | Mode | Grants authority |
|---|---|---|---|
| E12 | E1 | `belief_and_metacognition_advisory` | `false` |
| E12 | E7 | `belief_and_metacognition_advisory` | `false` |
| E12 | E9 | `belief_and_metacognition_advisory` | `false` |
| E4 | E1 | `preference_prediction_advisory` | `false` |
| E6 | E1 | `lesson_proposal_advisory` | `false` |
| E6 | E2 | `lesson_proposal_advisory` | `false` |

## Contract registry mirror

- Source: `docs/nerva2/CONTRACT_REGISTRY.json` (SHA-256 `01c490cc62a7550a5207eeb20e66c5ade25ec8847f3f4d716f0ffa316b39f7c9`)

| Contract | Status |
|---|---|
| `nerva.observation.v1` | `proposed` |
| `nerva.atlas.snapshot.v1` | `proposed` |
| `nerva.capability.v1` | `evolves_existing` |
| `nerva.decision.v1` | `proposed` |
| `nerva.action.v1` | `evolves_existing` |
| `nerva.episode.v1` | `proposed` |
| `nerva.lesson.v1` | `proposed` |
| `nerva.preference.v1` | `proposed` |
| `nerva.work-run.v1` | `candidate` |
| `nerva.scenario.v1` | `proposed` |
| `nerva.benchmark.v1` | `proposed` |
| `nerva.evidence.v1` | `evolves_existing` |

## Known source drift

- `runtime-feedback-e4-to-e1-registry-omission` is `open`: `E4 -> E1` appears in [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) but is absent from [`docs/nerva2/CONTRACT_REGISTRY.json`](../../docs/nerva2/CONTRACT_REGISTRY.json); reason `historical_registry_omits_documented_advisory_edge`.

## Reconciliation log

| Date | Id | Decision | Effect | Evidence |
|---|---|---|---|---|
| 2026-09-06 | `2026-09-06-981-safety-disabled` | movement_gate.enforcement_state required -> safety_disabled with a rollback record bound to PR #981 / 824ff187; four deleted control files move to registry_retired; scripts/check_nerva_program_manifest.py is restored as a compact advisory checker. | The manifest stops claiming an enforcement that CI no longer performs; dead registry paths become checker errors. | `docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md` · `scripts/check_nerva_program_manifest.py` · `.github/workflows/nerva-manifest-check.yml` |
| 2026-08-28 | `2026-08-28-a8-owner-host-cleared` | Owner cleared the A8 owner-host proof gate after a real-hardware run with good feedback; the E11 owner_live blocker is re-scoped to the post-tag A1 section 0 run record. | E11 stays blocked; the reason is narrower and names the artifact still owed. | `BACKLOG.md:3587` · `docs/HISTORY.md:386` · `docs/MANUAL_TESTING.md` |
| 2026-09-01 | `2026-09-01-918-retained` | PR #918 (B7 task mediation corrective, merge b5e52c6) RETAINED on main under a bounded owner exception, default-off; not program-accepted. | E5 and E8 keep the B7 program_gate blocker with an explanatory note; no authority change. | `BACKLOG.md:280` · `docs/HISTORY.md:384` |
| 2026-09-01 | `2026-09-01-1008-identity-manifest` | Issue #1008 owns Jarvis's own Identity Manifest (E4 identity-boundary lane, not Howard); #762 stays Howard-only. | E4 gains an issue reference; no gate or status change. | `docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md` · `docs/HISTORY.md:381` |
| 2026-09-06 | `2026-09-06-e5-candidate` | WITHDRAWN the same day, before merge. The row read: nerva.work-run.v1 moves to candidate on the E5.0 slice (work-run ledger, company supervisor, verifier, judge). It was written ahead of the code — none of work_runs.py, company_supervisor.py, work_verifier.py, work_judge.py or NIGHT_SHIFT_E5_0.md exist in the tree — so the claim, its evidence paths and the E5 status move described nothing. nerva.work-run.v1 stays proposed until the modules ship; E5 was already building/in_progress before this row, so the status move it described was not a move at all. | No status, gate or eligibility change at the time. The withdrawal is recorded rather than deleted so the attempted claim stays auditable. The modules shipped later the same day and the contract moved to candidate on that evidence — see the 2026-09-06-e5-shipped row. | `docs/nerva2/CONTRACT_REGISTRY.json` |
| 2026-09-06 | `2026-09-06-e5-shipped` | nerva.work-run.v1 moves to candidate on the E5.0 work-run chain, now in the tree: work_runs.py (durable ledger), work_verifier.py (evidence), work_judge.py (goal fit) and company_supervisor.py (the loop), default-off behind JARVIS_COMPANY_MODE with 80 hermetic tests. | Contract status only. Authority stays delegated_execution_only; E5 remains building/in_progress and every E5 delivery gate plus the B7 program gate stay open. Delivered, not program-accepted. | `docs/nerva2/CONTRACT_REGISTRY.json` · `docs/nerva2/NIGHT_SHIFT_E5_0.md` |

## Authority and integrity boundary

- This snapshot is evidence-only and cannot authorize or execute actions.
- Ultron remains the sole privileged-action authority.
- Runtime feedback is advisory and never becomes delivery or action authority.
- `done` and `satisfied` are repository-evidence labels, not owner-live or release proof.
- Release readiness remains `false`; typed owner-live, program, and external blockers remain visible above when present.
