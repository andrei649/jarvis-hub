# Continuity Core (#731) — cross-epic reconciliation

Status: `MAPPING ONLY — no implementation, no completion claim`
Parent program: #757 · Blocker plan: #778 (B3) · Source: #731 · Prior owner note: #731#issuecomment-5157184455

## What this document is

#778's B3 records Continuity Core (#731) as "valuable but orphaned from the formal
program" and lists six unblock items, all unchecked as of 2026-08-08. The owner's own
comment on #731 proposed the same five destinations and said the mapping "will be made
canonical during E0.3/program-manifest reconciliation" — E0.3 closed through #789/#790
without this specific follow-through landing. This document is that follow-through: it
converts #731 into a tracked cross-epic design source per B3's own alternative ("close it
only after every requirement has a destination and acceptance test" — this is the
"convert" branch, not the "close" branch; #731 stays open).

**This document does not:**
- implement any primitive, slice, or acceptance criterion below;
- grant completion to #731 or to any destination epic;
- change any epic's existing acceptance criteria;
- add dependency, runtime, provider, routing, or authority surface;
- move Ultron's status as sole privileged-action authority.

Every "prior art" citation below is existing accepted evidence on `main`, independently
reviewed and merged under its own PR. Citing it as relevant prior art is not the same as
claiming it satisfies the #731 requirement it is mapped against — gaps are called out
explicitly, not smoothed over.

## Epic issue map (for reference)

| Epic | Discovery issue | Bounded first-slice issue | Status (2026-08-08) |
|---|---|---|---|
| E2 Atlas | #760 | #781 (PR #794) | `BUILDING · E2.0 ACCEPTED` |
| E3 Episodes | #761 | #782 (PR #796), #798 (PR #799) | `BUILDING · E3.0 + E3.1 ACCEPTED` |
| E4 Howard | #762 | — | `NOT STARTED` |
| E5 Night Shift | #763 | — | `NOT STARTED` |
| E6 Reflection | #764 | #806 (PR #808), #820 (PR #823), #817 (PR #832) | `BUILDING` |
| E10 Experience | #768 | — | `NOT STARTED` |
| E11 Proof & Release | #769 | — | `NOT STARTED` |
| E12 Hybrid Cognition | #773 | — | tracked separately, advisory-only per #778 §2.2 |

## Primitive-by-primitive mapping

### 1. Identity Manifest → E4 / #762, with a gap

#731 asks for **Jarvis's own** identity contract (name, purpose, values, truthfulness,
boundaries, stable traits, relationship roles, goals/commitments, schema version, signed
history/migration/rollback). #762's current body is scoped entirely to **Howard** —
"an explainable, consent-aware model of how the owner tends to decide, communicate and
prioritize" — which is preference-prediction of Andrei, not Jarvis's own identity. B3's
own phrasing already anticipated this: "→ E4 Howard/identity boundary, **without merging
Howard with Nerva's own identity**."

**Gap, stated plainly:** no issue currently owns Jarvis's own Identity Manifest. #762
owns Howard only. This reconciliation does not create a new issue to fill that gap —
that is an owner-scoping decision (new E4 sub-scope vs. a distinct small issue), not a
documentation call this pass should make unilaterally.

### 2. Autobiographical Event Ledger → E2 / #760 + E3 / #761 (real prior art)

Accepted E2.0 (#781/PR #794) provides immutable `nerva.observation.v1` projections and
bounded `nerva.atlas.snapshot.v1` results with source provenance, confidence, privacy
class and temporal validity — the same fields #731 lists for ledger events. Accepted
E3.0 (#782/PR #796) provides typed episode/reference/assertion/audit values with
deletion lineage and correction/merge/split/tombstone semantics — matching #731's
"correction/supersession relationship rather than silent overwrite."

**Gap:** neither #760 nor #761 names an "append-only autobiographical event ledger" as
its own artifact; the overlap is structural, not a literal 1:1 contract match. #731's
`event_id` / observed-vs-recorded time / actor / channel / observed-inferred-simulated
classification fields are not yet individually pinned to either issue's acceptance list.

### 3. Self-model and autobiography → split across E4 (gap), E3 / #761, E12 / #773

"Current self-state" and "enduring identity anchors" fall into the same E4 gap as #1.
"Life chapters," "active relationships and shared history," and "open loops and
promises" overlap accepted E3.0's episode/lifecycle model. "Beliefs with temporal
versions" and the "uncertainty ledger" belong under E12 (#773, Hybrid Cognition),
which #778 §2.2 already scopes as calibration/belief-and-metacognition input to
Cortex — advisory only, never authority.

### 4. Life loop → already reconciled at the architecture level

#731's loop (Observe → Interpret → Remember → Reflect → Plan → Act → Verify → Learn) is
structurally the same shape as #778 §2.2's existing runtime cognitive feedback graph
(`Observe → Atlas → Cortex → Ultron → Synapse/Executors → Verify → Episodes → Outcomes
→ Evidence`, with Reflection feeding back advisory-only). This is the one primitive
where the target-state architecture and #731's ask were already the same graph before
this document existed — worth recording explicitly so it isn't rediscovered as a "new"
design question later. The gap is entirely in runtime implementation, not in mapping.

### 5. Proactivity engine (time-ROI budget) → E5 / #763 + E10 / #768 (strongest prior art)

#778's own M4 section already carries #731's time-ROI formula **verbatim**:
`expected_time_saved × confidence + expected_risk_avoided − setup_cost −
interruption_cost − maintenance_cost`. #763's Build list ("goal backlog and opportunity
discovery," "value/risk/cost prioritization," budget/deadline/stop conditions) and
acceptance ("Three recurring workflows show reliable owner value over a multi-night
trial") already match #731's Slice D almost line for line. #768's Build list ("Night
Shift morning brief," "evidence-linked completion and failure cards") matches #731's
per-intervention result/evidence reporting. This is the most completely reconciled
primitive in the set — the formula and acceptance shape are already canonical; only
implementation is outstanding.

### 6. Portable Continuity Bundle → E11 / #769, with a content-detail gap

#769's "Required proof" already lists backup/restore, export/delete, and
upgrade/rollback drills, which is the right home. But #731's bundle contents are far
more specific than #769's current bullets: identity anchors + SOUL history +
autobiographical ledger + memory tiers/core blocks + graph export + embedding metadata
(explicitly *not* embedding-only truth) + skills/tool contracts + privacy scopes + eval
fixtures + migration log + integrity hashes. #769 does not yet enumerate bundle
contents at this granularity.

**Gap:** the destination is right; the acceptance criteria are not yet detailed enough
to test #731's specific bundle-content list. That detailing is E11's own future work,
not something this reconciliation should pre-write into #769 unilaterally.

### 7. Memory trust / admission gate → E3 / #761 + E6 / #764 + E12 / #773

#764's acceptance already includes "Contradictions are surfaced rather than averaged
away," a direct match to #731's contradiction/supersession check. E3.0's typed
provenance/confidence values are relevant prior art. E12/#773 is the natural home for
the calibration/abstention half ("whether abstention is safer").

**Gap, and the one worth flagging most clearly:** #731's trust-gate checklist includes
**"instruction-vs-data taint"** — treating recalled memory content as data, never as
executable instruction. No destination issue (#761, #764, or #773) currently names this
check anywhere in its acceptance criteria. This is a prompt-injection-adjacent concern
directly relevant to Episodes/Reflection recall paths, and it currently has no owner.
Recorded here rather than silently dropped; assigning it is an owner/security-architect
decision, not one this document makes unilaterally.

## Delivery slices A–E

| Slice | Destination | Prior art | Gap |
|---|---|---|---|
| A — schema and ledger | E2 + E3 | `nerva.observation.v1`, `nerva.atlas.snapshot.v1`, `nerva.episode.v1` cover versioned schema, append/correct/supersede, provenance, temporal validity | export/import round-trip test not yet proven — E3's own "residual risks" says so |
| B — identity and autobiography | E4 (gap) | none | see primitive 1/3 gap above |
| C — trusted recall | E3 + E6 | typed provenance (E3.0), contradiction-surfacing acceptance (E6) | admission-gate taint check gap above |
| D — proactive relief loop | E5 + E10 | time-ROI formula, Build/acceptance shape already match | implementation not started (`NOT STARTED`) |
| E — migration harness | E11 | backup/restore/export/delete/rollback drills named | bundle-content detail gap above |

## Acceptance criteria (10) — destination and current evidence

1. Restart preserves identity/commitments/relationships → E4 (gap) + E3 (partial: episode lifecycle exists, no restart-continuity proof yet).
2. Model replacement preserves continuity eval baseline → E11 (no eval baseline defined yet).
3. Corrected fact never resurfaces as current truth → E3.0 supersession/tombstone semantics are directly relevant, already accepted.
4. Every recalled memory explains source/time/confidence/admission reason → E3 (provenance exists) + E6/E12 (admission-reason explainability not yet built).
5. Distinguish observed/inferred/simulated → no destination issue currently names this three-way classification explicitly; closest fit is E2's observation provenance.
6. Family-domain isolation → not covered by any Nerva 2.0 epic issue read for this document; #731 names Frigga as a separate, stricter-privacy domain outside Jarvis/Nerva identity — likely an owner-scoping question rather than an E-epic fit.
7. Export→wipe→import without embedding-model lock-in → E11 (gap, same as bundle content above).
8. Proactive suggestions rate-limited and measured by verified net time saved → E5/E10, strong prior art (see primitive 5).
9. System can say "I do not know / may misremember" → E12 calibration, advisory-only per #778 §2.2.
10. No identity change becomes authoritative without versioned proposal + governance → E4 (gap) + Ultron's existing sole-authority boundary already structurally prevents silent authority changes, independent of this document.

## Evaluation suite

#731's evaluation suite (multi-session recall, temporal reasoning, contradiction/
retraction handling, cross-topic/person leakage, abstention calibration, identity
consistency across base models, privacy boundary tests, proactive precision/interruption
burden, migration parity) maps naturally to **E9 Research Lab** (#784) as the harness
that would run it — E9's own stream description is "continuous model/tool benchmark
harness using real Nerva task suites." This connection is not stated anywhere in #731,
#778 B3, or the owner's #731 comment; it is this document's own inference, flagged as
such rather than presented as an existing decision. E9.0/#784/PR #803 and E9.1/#807/
PR #809 are accepted evaluation-only foundations that a future Continuity Core suite
could plausibly reuse, subject to the owner or an independent reviewer confirming the
fit.

## Next smallest slice

Per #731's own "First implementation decision": begin with the canonical event ledger,
identity manifest, trust gate, and migration test — not fine-tuning. Given the mapping
above, the smallest concretely executable next step is **not** a new Continuity Core
slice directly; it is resolving the Identity Manifest destination gap (primitive 1),
since three other gaps (self-model anchors, acceptance criteria 1 and 10) all depend on
it. That is an owner-scoping decision (extend #762's scope with an explicit boundary
section, or open a new small issue) rather than something this reconciliation should
decide unilaterally.

## Status after this document

B3's six unblock items now each have an explicit destination, prior-art citation where
one exists, and an honestly stated gap where one doesn't. None of the five destination
epics gained a typed contract or acceptance test *from this document* — those remain
each epic's own future bounded slice. #731 remains open, per its own "close it only
after every requirement has a destination and acceptance test" bar not yet being met —
destinations now exist; acceptance tests mostly do not.
