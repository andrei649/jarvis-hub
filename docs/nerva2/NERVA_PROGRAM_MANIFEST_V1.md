# Nerva program manifest v1

> Offline repository evidence snapshot. This document does not query live GitHub, does not authorize execution, does not declare program completion, and does not establish release readiness.

- The JSON manifest is the sole current dependency/status/gate/blocker/runtime truth.
- Evidence baseline: `458df5afabdf12536236522034e7c84493200147`
- Observed at (mutable snapshot context): `2026-08-06T06:19:08Z`
- Program issue: [#757](https://github.com/andrei649/jarvis-hub/issues/757)
- Blocker plan: [#778](https://github.com/andrei649/jarvis-hub/issues/778)
- Manifest control: [#839](https://github.com/andrei649/jarvis-hub/issues/839)
- Live issue state verified by this checker: `false`

## Program status and derived delivery eligibility

| Stream | Epic | Program status | Delivery eligibility | Completion evidence |
|---|---:|---|---|---|
| E0 — Baseline and migration map | [#758](https://github.com/andrei649/jarvis-hub/issues/758) | `done` | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E1 — Cortex meta-decision and capability routing | [#759](https://github.com/andrei649/jarvis-hub/issues/759) | `building` | `in_progress` | — |
| E2 — Atlas unified reality graph | [#760](https://github.com/andrei649/jarvis-hub/issues/760) | `building` | `in_progress` | — |
| E3 — Episodes experience-centric memory | [#761](https://github.com/andrei649/jarvis-hub/issues/761) | `building` | `in_progress` | — |
| E4 — Howard digital twin and preference model | [#762](https://github.com/andrei649/jarvis-hub/issues/762) | `not_started` | `blocked` | — |
| E5 — Night Shift autonomous work loop | [#763](https://github.com/andrei649/jarvis-hub/issues/763) | `not_started` | `blocked` | — |
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
| E1 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E2 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E3 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E3 | E2 | `satisfied` | [`9a13a0241fb65d01809f539f1048944ea01a3bf5`](https://github.com/andrei649/jarvis-hub/commit/9a13a0241fb65d01809f539f1048944ea01a3bf5) (immutable commit) · [#781](https://github.com/andrei649/jarvis-hub/issues/781) (mutable context) · [#795](https://github.com/andrei649/jarvis-hub/pull/795) (mutable context) · [`docs/nerva2/ATLAS_E2_0.md` at `9a13a0241fb6`](https://github.com/andrei649/jarvis-hub/blob/9a13a0241fb65d01809f539f1048944ea01a3bf5/docs/nerva2/ATLAS_E2_0.md) (immutable blob locator) · Atlas minimum for Episodes accepted |
| E4 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E4 | E3 | `unsatisfied` | — |
| E5 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E5 | E1 | `unsatisfied` | — |
| E5 | E2 | `unsatisfied` | — |
| E5 | E3 | `unsatisfied` | — |
| E5 | E6 | `unsatisfied` | — |
| E6 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E6 | E3 | `satisfied` | [`a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f`](https://github.com/andrei649/jarvis-hub/commit/a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f) (immutable commit) · [#806](https://github.com/andrei649/jarvis-hub/issues/806) (mutable context) · [#823](https://github.com/andrei649/jarvis-hub/pull/823) (mutable context) · [`docs/nerva2/REFLECTION_E6_0.md` at `a33c9a5db5cc`](https://github.com/andrei649/jarvis-hub/blob/a33c9a5db5cc4b1e2f1849ebc39e28d197f66b5f/docs/nerva2/REFLECTION_E6_0.md) (immutable blob locator) · Episodes minimum for Reflection accepted |
| E7 | E1 | `unsatisfied` | — |
| E7 | E2 | `unsatisfied` | — |
| E7 | E3 | `unsatisfied` | — |
| E7 | E4 | `unsatisfied` | — |
| E8 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E9 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E10 | E1 | `unsatisfied` | — |
| E10 | E2 | `unsatisfied` | — |
| E10 | E5 | `unsatisfied` | — |
| E10 | E6 | `unsatisfied` | — |
| E11 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
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
| E12 | E0 | `satisfied` | [`ec2c281a9bc800bc1152f9cef865eca3be2a5fd4`](https://github.com/andrei649/jarvis-hub/commit/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4) (immutable commit) · [#758](https://github.com/andrei649/jarvis-hub/issues/758) (mutable context) · [#790](https://github.com/andrei649/jarvis-hub/pull/790) (mutable context) · [`docs/nerva2/E0_COMPLETION.json` at `ec2c281a9bc8`](https://github.com/andrei649/jarvis-hub/blob/ec2c281a9bc800bc1152f9cef865eca3be2a5fd4/docs/nerva2/E0_COMPLETION.json) (immutable blob locator) · E0 control gate accepted |
| E12 | E1 | `unsatisfied` | — |
| E12 | E2 | `unsatisfied` | — |
| E12 | E3 | `unsatisfied` | — |
| E12 | E6 | `unsatisfied` | — |
| E12 | E9 | `unsatisfied` | — |

A satisfied delivery edge requires an accepted 40-hex commit, an artifact present at that commit, and mutable issue/PR context. An upstream epic's overall status is never substituted for consumer-specific gate acceptance.

## Typed blockers

| Stream | Kind | Target | Evidence context | Reason |
|---|---|---|---|---|
| E4 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E5 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E5 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E5 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E5 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E5 | `program_gate` | `B7` | [#818](https://github.com/andrei649/jarvis-hub/issues/818) · [`BACKLOG.md`](../../BACKLOG.md) | Task-mediation decisions remain unresolved. |
| E7 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E7 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E7 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E7 | `delivery_gate` | `E4` | [#762](https://github.com/andrei649/jarvis-hub/issues/762) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E8 | `external_dependency` | `E8_1C` | [#804](https://github.com/andrei649/jarvis-hub/issues/804) · [`docs/nerva2/EXECUTION_PROVIDER_E8_1A.md`](../../docs/nerva2/EXECUTION_PROVIDER_E8_1A.md) | Execution-provider preflight is not accepted. |
| E8 | `external_dependency` | `PROVIDER_E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/RESEARCH_LAB_E9_1.md`](../../docs/nerva2/RESEARCH_LAB_E9_1.md) | Provider-specific evidence is missing. |
| E8 | `program_gate` | `B7` | [#818](https://github.com/andrei649/jarvis-hub/issues/818) · [`BACKLOG.md`](../../BACKLOG.md) | Task-mediation decisions remain unresolved. |
| E10 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E10 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E10 | `delivery_gate` | `E5` | [#763](https://github.com/andrei649/jarvis-hub/issues/763) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E10 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E10` | [#768](https://github.com/andrei649/jarvis-hub/issues/768) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E12` | [#773](https://github.com/andrei649/jarvis-hub/issues/773) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E4` | [#762](https://github.com/andrei649/jarvis-hub/issues/762) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E5` | [#763](https://github.com/andrei649/jarvis-hub/issues/763) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E7` | [#765](https://github.com/andrei649/jarvis-hub/issues/765) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E8` | [#766](https://github.com/andrei649/jarvis-hub/issues/766) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `delivery_gate` | `E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E11 | `owner_live` | `OWNER_LIVE` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/nerva2/RISKS.md`](../../docs/nerva2/RISKS.md) | Owner-host live proof is missing. |
| E11 | `program_gate` | `RECURRING_WORKFLOWS` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/nerva2/RISKS.md`](../../docs/nerva2/RISKS.md) | Recurring-workflow proof is missing. |
| E11 | `program_gate` | `RESTORE_SOAK` | [#769](https://github.com/andrei649/jarvis-hub/issues/769) · [`docs/nerva2/RISKS.md`](../../docs/nerva2/RISKS.md) | Restore and soak proof is missing. |
| E12 | `delivery_gate` | `E1` | [#759](https://github.com/andrei649/jarvis-hub/issues/759) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E12 | `delivery_gate` | `E2` | [#760](https://github.com/andrei649/jarvis-hub/issues/760) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E12 | `delivery_gate` | `E3` | [#761](https://github.com/andrei649/jarvis-hub/issues/761) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E12 | `delivery_gate` | `E6` | [#764](https://github.com/andrei649/jarvis-hub/issues/764) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |
| E12 | `delivery_gate` | `E9` | [#767](https://github.com/andrei649/jarvis-hub/issues/767) · [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) | Consumer-specific upstream gate evidence is not accepted. |

## Runtime feedback — advisory only

| Source | Consumer | Mode | Grants authority |
|---|---|---|---|
| E12 | E1 | `belief_and_metacognition_advisory` | `false` |
| E12 | E7 | `belief_and_metacognition_advisory` | `false` |
| E12 | E9 | `belief_and_metacognition_advisory` | `false` |
| E4 | E1 | `preference_prediction_advisory` | `false` |
| E6 | E1 | `lesson_proposal_advisory` | `false` |
| E6 | E2 | `lesson_proposal_advisory` | `false` |

## Known source drift

- `runtime-feedback-e4-to-e1-registry-omission` is `open`: `E4 -> E1` appears in [`docs/nerva2/DEPENDENCIES.md`](../../docs/nerva2/DEPENDENCIES.md) but is absent from [`docs/nerva2/CONTRACT_REGISTRY.json`](../../docs/nerva2/CONTRACT_REGISTRY.json); normalized source SHA-256 `39f8717a747e4ef6802611cde18fa4fd76b740839c765e3737a365ac62a821fc`.

## Authority and integrity boundary

- This snapshot is evidence-only and cannot authorize or execute actions.
- Ultron remains the sole privileged-action authority.
- Runtime feedback is advisory and never becomes delivery or action authority.
- `done` and `satisfied` are repository-evidence labels, not owner-live or release proof.
- Release readiness remains `false`; typed owner-live, program, and external blockers remain visible above when present.
