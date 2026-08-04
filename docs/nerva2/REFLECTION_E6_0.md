# Nerva E6.0 — evidence-bound outcome comparison and LessonProposal contract

Status: draft implementation evidence for #806 / #764. This document does not
claim Reflection epic completion, calibrated confidence, or any Night Shift
readiness.

## Purpose

E6.0 adds the smallest Reflection foundation: compare an expected outcome with
retained observed/verified outcome evidence, and emit a typed, reversible
`nerva.lesson.v1` proposal. Reflection may propose a lesson. It cannot rewrite
source evidence, promote its own proposal, authorize an action, execute work, or
mark work complete.

## Dependency and authority boundary

- prerequisites: accepted E3.0 / #782 and E3.1 / #798, both already in `main`;
- base revision: `main@5bd996f83f9a5cca10fa49d0c680b851c18139e8` (E9.0 / #803);
- contract authority is fixed to `proposal_only`;
- Episodes remains `memory_record_only` and the owner of experience memory;
- Atlas remains the owner of canonical fact/state projections;
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

The authority ceiling is expressed as immutable `init=False` dataclass fields and
is therefore serialized into every record and replay fingerprint:

```text
can_rewrite_source_evidence = false
can_promote_lesson          = false
can_authorize               = false
can_execute                 = false
can_mark_complete           = false
```

## Reused implementation

The package reuses rather than rebuilds:

- `EpisodeReference` and its content-free pointer, tombstone and integrity rules
  from the accepted E3.0 Episodes contract;
- `AtlasConfidence` and `PrivacyClass` from `agents/core/memory/atlas_snapshot.py`,
  so missing evidence stays qualified instead of becoming a guessed number;
- the canonical-JSON and SHA-256 replay-fingerprint convention established by
  E1.0 `nerva.decision.v1` in `agents/core/cortex_decision.py`;
- the existing `tests/test_daily_reflection.py` regression surface.

No second memory store, scorer, scheduler, permission system, or reflector is
introduced. `DailyReflector` production behavior is untouched.

## Records

### `nerva.outcome-observation.v1` — `OutcomeObservation`

Immutable comparison of one expected decision reference against observed outcome
references. It carries the environment, explicit evidence limitations, privacy
class, qualified confidence, and one of four comparison statuses:

```text
confirmed | refuted | contradictory | insufficient_evidence
```

`compare_outcome()` derives the status deterministically. An unjudged live
reference is never guessed into a verdict — it forces `insufficient_evidence`
and records why in `evidence_limitations`.

### `nerva.lesson.v1` — `LessonProposal`

Immutable bounded claim with supporting and counter-evidence reference IDs,
observation IDs, qualified confidence, scope, applicability, review/expiry dates,
contradiction links, proposed destinations, and lifecycle:

```text
proposed | accepted_by_destination | rejected | expired | superseded
```

### `nerva.lesson.audit.v1` — `LessonAuditEvent`

Every lifecycle transition returns an audit event retaining the prior revision,
prior replay fingerprint, and the **exact prior canonical payload**, so a
transition is fully reversible via `restore_prior()`.

## Fail-closed validation

The contract rejects, rather than normalizes:

| Rejected condition | Behavior |
|---|---|
| Expected reference that is not a `decision` role | `ValueError` |
| Outcome evidence predating its own decision | `ValueError` |
| `confirmed`/`refuted` without live outcome evidence | `ValueError` |
| `contradictory` with fewer than two live outcomes | `ValueError` |
| `insufficient_evidence` alongside live evidence | `ValueError` |
| Privacy class below the escalated evidence privacy | `ValueError` |
| A forged `observation_id` or `proposal_id` | `ValueError` |
| Evidence that both supports and counters one claim | `ValueError` |
| Confidence supplied as a bare float | `ValueError` |
| A proposal built only from insufficient/refuted evidence | `ValueError` |
| Reflection acting as the promoting actor | `ValueError` |
| Acceptance without a targeted destination | `ValueError` |
| Expiry backdated before `expires_at` | `ValueError` |
| Supersession without a named replacement | `ValueError` |
| Any transition out of a terminal state | `ValueError` |

Tombstoned references are never live evidence, so deleted sources cannot keep a
proposal alive.

## Privacy controls

Privacy escalates with combined evidence and can never downgrade. A proposal
derived from `restricted` evidence may only target the `human_review`
destination; routing it to `episodes`, `howard`, `synapse` or `experience` is
rejected. Free-text `claim` and `scope` are length-bounded.

## Destination separation

Promotion is structurally separate and absent by default. `transition_lesson()`
refuses acceptance when the actor is Reflection itself, and requires an explicit
destination that the proposal actually targets. Reaching
`accepted_by_destination` records the destination's own decision; it does not
write to Episodes, Atlas or Howard.

## Test surface and test-count neutrality

The repository pins its generated test count. Following the E3.0/E3.1 convention,
the bounded assertions live in `tests/_nerva_e6_0_checks.py` and are invoked from
the existing `tests/test_daily_reflection.py` regression, so the collected test
count is unchanged (5767 before and after). Ten assertion groups cover the four
comparison paths, deterministic fingerprints, immutability and authority flags,
insufficient-evidence fail-closure, evidence/chronology validation, privacy
non-downgrade, self-promotion refusal, reversible lifecycle audit, counter-
evidence retention, and canonical serialization.

## What this slice is not

- not automatic lesson promotion or a canonical memory write;
- not consolidation, forgetting, compaction or contradiction repair;
- not a production scheduler, Night Shift or owner-notification integration;
- not an LLM-generated lesson;
- not calibrated confidence — confidence is qualified but uncalibrated;
- not E6 epic completion and not an E5 unblock on its own.

## Residual risks

A proposal can still encode a misleading interpretation despite correct
provenance. Confidence is initially uncalibrated. The single hermetic fixture may
overfit. Free-text claims remain a privacy surface bounded only by length and
privacy class. Destination modules may later promote too permissively; that risk
belongs to the destination slice, not to this contract.

## Migration and rollback

The change is purely additive: one new module, one new test helper, four added
lines in an existing test, and this document. Rollback is one atomic revert of
those files. No data migration, no schema change to existing records, and no
compensating external action is required. Existing Episode, Atlas, run-history,
feedback and `DailyReflector` data is neither rewritten nor deleted.

## Next coherent package

After E6.0 acceptance, run one separate evaluation-only comparison between
proposed lessons and held-out outcomes before integrating promotion,
consolidation, forgetting, Night Shift or production scheduling.
